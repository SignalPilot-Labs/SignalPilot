"""Successful-thread emitter: one ledger row per terminal chat run.

Called from the chat run finalizer (``store.standalone_chat.lifecycle``)
inside the transaction that writes the terminal run status. Writes ``-50``
with reason ``ok``, or ``0`` with the first matching non-billable reason:

``failed``        the run ended failed or cancelled
``tuning``        the run's user is listed in the org setting ``tuning_users``
``zero_queries``  no governed query of this run reached the warehouse
``low_evidence``  fewer than ``EVIDENCE_THRESHOLD`` of the run's warehouse
                  queries are evidence-backed
``repeat``        the same normalized prompt by the same user produced a
                  billed (``ok``) or free-repeat thread in the last 24 hours

Governed query count
    The number of ``query`` ledger rows with ``ref_type = 'chat_run'`` and
    ``ref_id = run_id`` whose credits are negative (reason ``ok``). Query rows
    are written by ``emitters.queries`` in the executor's own transaction, so
    they are committed before the finalizer runs.

Evidence-backed query
    A query is evidence-backed when its result was available to the answer:
    ``GatewayGovernedQueryExecution`` with status ``completed`` and a stored
    ``GatewayStructuredQueryResult`` or ``GatewayRuntimeDataset``. When the
    final message's ``metadata_json`` carries ``cited_result_ids`` (the
    attribution projection, when it lands), only executions whose result id
    is in that list count. Evidence share = evidence-backed / warehouse
    queries (the ``ok`` query rows).

Repeat
    ``prompt_hash`` = sha256 of the user's message lower-cased, punctuation
    stripped, whitespace collapsed. It is stored in the thread row's payload;
    the check looks for a prior ``thread`` row of the same org and user with
    the same payload hash, reason ``ok`` or ``repeat``, occurred in the last
    24 hours.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ledger import LedgerEntry
from ..models import GatewayCreditLedger
from ..rates import THREAD_CREDITS
from ._base import json_safe_payload, metered_entitlement, never_raises, write_in_savepoint

EVIDENCE_THRESHOLD = 0.8
REPEAT_WINDOW = timedelta(hours=24)

REASON_OK = "ok"
REASON_FAILED = "failed"
REASON_TUNING = "tuning"
REASON_ZERO_QUERIES = "zero_queries"
REASON_LOW_EVIDENCE = "low_evidence"
REASON_REPEAT = "repeat"

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize_prompt(text: str | None) -> str:
    """Lower-case, strip punctuation, collapse whitespace."""
    cleaned = _PUNCTUATION.sub(" ", (text or "").lower())
    return _WHITESPACE.sub(" ", cleaned).strip()


def prompt_hash(text: str | None) -> str:
    return hashlib.sha256(normalize_prompt(text).encode("utf-8")).hexdigest()


async def governed_query_count(session: AsyncSession, *, org_id: str, run_id: str) -> int:
    """Count the run's billed (``ok``) query ledger rows."""
    stmt = select(func.count()).where(
        GatewayCreditLedger.org_id == org_id,
        GatewayCreditLedger.unit == "query",
        GatewayCreditLedger.ref_type == "chat_run",
        GatewayCreditLedger.ref_id == run_id,
        GatewayCreditLedger.credits < 0,
    )
    return int((await session.execute(stmt)).scalar_one() or 0)


async def evidence_backed_count(
    session: AsyncSession, *, org_id: str, run_id: str, cited_result_ids: set[str] | None
) -> int:
    """Count the run's completed executions whose result was available (or cited)."""
    from gateway.db.models import (
        GatewayGovernedQueryExecution,
        GatewayRuntimeDataset,
        GatewayStructuredQueryResult,
    )

    stmt = (
        select(GatewayGovernedQueryExecution.id, GatewayStructuredQueryResult.id, GatewayRuntimeDataset.id)
        .outerjoin(
            GatewayStructuredQueryResult,
            GatewayStructuredQueryResult.execution_id == GatewayGovernedQueryExecution.id,
        )
        .outerjoin(
            GatewayRuntimeDataset,
            GatewayRuntimeDataset.query_execution_id == GatewayGovernedQueryExecution.id,
        )
        .where(
            GatewayGovernedQueryExecution.org_id == org_id,
            GatewayGovernedQueryExecution.run_id == run_id,
            GatewayGovernedQueryExecution.status == "completed",
        )
    )
    rows = (await session.execute(stmt)).all()
    count = 0
    for execution_id, result_id, dataset_id in rows:
        if cited_result_ids is not None:
            if result_id in cited_result_ids or dataset_id in cited_result_ids or execution_id in cited_result_ids:
                count += 1
        elif result_id is not None or dataset_id is not None:
            count += 1
    return count


async def is_repeat(session: AsyncSession, *, org_id: str, user_id: str, digest: str, now: datetime) -> bool:
    stmt = (
        select(GatewayCreditLedger.id)
        .where(
            GatewayCreditLedger.org_id == org_id,
            GatewayCreditLedger.user_id == user_id,
            GatewayCreditLedger.unit == "thread",
            GatewayCreditLedger.reason.in_((REASON_OK, REASON_REPEAT)),
            GatewayCreditLedger.occurred_at >= now - REPEAT_WINDOW,
            GatewayCreditLedger.payload["prompt_hash"].as_string() == digest,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _user_prompt(session: AsyncSession, run: Any) -> str:
    from gateway.db.models import GatewayChatMessage

    message_id = getattr(run, "user_message_id", None)
    if not message_id:
        return ""
    row = (await session.execute(select(GatewayChatMessage.content).where(GatewayChatMessage.id == message_id))).first()
    return str(row[0]) if row and row[0] else ""


async def _tuning_users(session: AsyncSession, org_id: str) -> set[str]:
    from gateway.store.settings import load_settings

    settings = await load_settings(session, org_id=org_id)
    return {str(user) for user in (getattr(settings, "tuning_users", None) or [])}


def _cited_result_ids(final_message: Any) -> set[str] | None:
    metadata = getattr(final_message, "metadata_json", None) if final_message is not None else None
    if not isinstance(metadata, dict):
        return None
    cited = metadata.get("cited_result_ids")
    if not isinstance(cited, list):
        return None
    return {str(value) for value in cited}


@never_raises
async def emit_thread_credit(
    session: AsyncSession,
    run: Any,
    *,
    final_message: Any = None,
    entitlement: Any = None,
    now: datetime | None = None,
) -> int | None:
    """Write the thread ledger row for a terminal run in ``session``.

    ``run`` is the ``GatewayChatRun`` with its terminal status already set.
    Returns the new ledger id, or None when nothing was written.
    """
    org_id = str(getattr(run, "org_id", "") or "")
    run_id = str(getattr(run, "id", "") or "")
    if not org_id or not run_id:
        return None
    if await metered_entitlement(org_id, entitlement) is None:
        return None

    now = now or datetime.now(UTC)
    user_id = str(getattr(run, "user_id", "") or "")
    status = str(getattr(run, "status", "") or "")
    digest = prompt_hash(await _user_prompt(session, run))
    queries = 0
    evidence = 0
    share: float | None = None

    if status != "completed":
        reason = REASON_FAILED
    elif user_id in await _tuning_users(session, org_id):
        reason = REASON_TUNING
    else:
        queries = await governed_query_count(session, org_id=org_id, run_id=run_id)
        if queries == 0:
            reason = REASON_ZERO_QUERIES
        else:
            evidence = await evidence_backed_count(
                session, org_id=org_id, run_id=run_id, cited_result_ids=_cited_result_ids(final_message)
            )
            share = min(1.0, evidence / queries)
            if share < EVIDENCE_THRESHOLD:
                reason = REASON_LOW_EVIDENCE
            elif await is_repeat(session, org_id=org_id, user_id=user_id, digest=digest, now=now):
                reason = REASON_REPEAT
            else:
                reason = REASON_OK

    credits = -THREAD_CREDITS if reason == REASON_OK else 0
    payload = json_safe_payload(
        {
            "run_id": run_id,
            "conversation_id": getattr(run, "conversation_id", None),
            "project_id": getattr(run, "project_id", None),
            "status": status,
            "error_code": getattr(run, "public_error_code", None),
            "prompt_hash": digest,
            "governed_queries": queries,
            "evidence_backed": evidence,
            "evidence_share": round(share, 4) if share is not None else None,
        }
    )
    entry = LedgerEntry(
        org_id=org_id,
        entry_type="consume",
        credits=credits,
        unit="thread",
        quantity=1,
        reason=reason,
        source="chat",
        idempotency_key=f"thread:{run_id}",
        occurred_at=getattr(run, "terminal_at", None) or now,
        ref_type="chat_run",
        ref_id=run_id,
        user_id=user_id or None,
        payload=payload,
    )
    return await write_in_savepoint(session, entry)


__all__ = [
    "EVIDENCE_THRESHOLD",
    "REPEAT_WINDOW",
    "emit_thread_credit",
    "evidence_backed_count",
    "governed_query_count",
    "is_repeat",
    "normalize_prompt",
    "prompt_hash",
]
