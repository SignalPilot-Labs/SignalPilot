"""Governed query emitter: one ledger row per governed execution.

What counts
-----------
The anchor row is ``GatewayGovernedQueryExecution``: the governed path creates
exactly one of these per statement that is about to reach the customer's
warehouse (Track A ``query_executor`` and Track B ``runtime_datasets``).
Schema and metadata calls (``get_schema``, ``list_tables``, dbt map compiles,
readiness probes) never create an execution row and therefore never reach
this emitter. ``COUNTED_QUERY_PATHS`` lists every ``query_path`` value that
can appear on an execution row; anything else is ignored.

The audit log's ``sql`` rows are written best-effort in the background from
the connector, in a separate session, and there are several of them per
execution (started, progress, completed events on chat runs). The execution
row is the only durable one-per-execution record, so the idempotency key is
``query:{execution_id}`` and the row is written in the same transaction as
the execution's terminal state.

Credits
-------
* ``-1`` reason ``ok``: the statement reached the warehouse. That is status
  ``completed``, plus the route rejections that ran the statement and then
  refused the result (``WAREHOUSE_EXECUTED_ERROR_CODES``).
* ``0`` reason ``blocked``: the statement never ran, was refused by the
  warehouse, timed out, or was cancelled.
* ``0`` reason ``service_identity``: gateway self-initiated work
  (``billing.identity.is_service_identity``).

Source attribution (``SOURCE_RULES``, first match wins)
-------------------------------------------------------
1. The MCP eval context var is set (``mcp_eval_run_var``)  -> ``eval``
2. ``execution.user_id == "eval-runner"``                     -> ``eval``
3. ``query_path == "dashboard"``                              -> ``dashboard``
4. ``execution.run_id`` is set (any path inside a chat run)   -> ``chat``
5. ``query_path == "mcp"`` (Claude Code / MCP client)         -> ``mcp``
6. ``query_path in ("sdk", "direct_api")`` (notebook SDK, REST)-> ``notebook``
7. anything else                                              -> ``system``

Callers may pass ``source`` explicitly (a scheduler running a saved query
passes ``schedule``); the rules above are the fallback.

Blocks that happen before an execution row exists (SQL validation on the
raw text) are not recorded: there is no anchor id, and the audit log already
carries them with ``blocked=True``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..identity import is_service_identity
from ..ledger import LedgerEntry
from ._base import json_safe_payload, metered, never_raises, write_in_savepoint

# Every query_path a GatewayGovernedQueryExecution row can carry.
COUNTED_QUERY_PATHS: frozenset[str] = frozenset({"direct_api", "mcp", "sdk", "dashboard", "dataset_ref"})

# Terminal error codes whose statement did run on the warehouse before the
# gateway refused the result. These still cost one credit.
WAREHOUSE_EXECUTED_ERROR_CODES: frozenset[str] = frozenset(
    {
        "runtime_required",
        "aggregate_required",
        "result_too_large",
        "result_persistence_failed",
        "dataset_persistence_failed",
    }
)

REASON_OK = "ok"
REASON_BLOCKED = "blocked"
REASON_SERVICE = "service_identity"

EVAL_RUNNER_USER_ID = "eval-runner"


def _eval_context_active() -> bool:
    try:
        from gateway.mcp.context import mcp_eval_run_var

        return bool(mcp_eval_run_var.get(None))
    except Exception:
        return False


def derive_source(execution: Any) -> str:
    """Map an execution row onto a ledger ``source`` (see the module docstring)."""
    path = str(getattr(execution, "query_path", "") or "")
    if _eval_context_active() or getattr(execution, "user_id", None) == EVAL_RUNNER_USER_ID:
        return "eval"
    if path == "dashboard":
        return "dashboard"
    if getattr(execution, "run_id", None):
        return "chat"
    if path == "mcp":
        return "mcp"
    if path in ("sdk", "direct_api"):
        return "notebook"
    return "system"


def query_outcome(execution: Any, query_credits: int) -> tuple[int, str]:
    """Return ``(credits, reason)`` for a terminal execution row."""
    status = str(getattr(execution, "status", "") or "")
    code = getattr(execution, "public_error_code", None)
    if status == "completed" or (status == "failed" and code in WAREHOUSE_EXECUTED_ERROR_CODES):
        return -query_credits, REASON_OK
    return 0, REASON_BLOCKED


def _ref(execution: Any) -> tuple[str, str]:
    run_id = getattr(execution, "run_id", None)
    if run_id:
        return "chat_run", str(run_id)
    return "query_execution", str(execution.id)


@never_raises
async def emit_query_credit(
    session: AsyncSession,
    execution: Any,
    *,
    source: str | None = None,
    entitlement: Any = None,
) -> int | None:
    """Write the ledger row for one terminal governed execution in ``session``.

    Call it right before the commit that persists the execution's terminal
    status. Returns the new ledger id, or None when nothing was written (not
    metered, duplicate key, or a swallowed failure).
    """
    org_id = str(getattr(execution, "org_id", "") or "")
    if not org_id:
        return None
    if str(getattr(execution, "query_path", "") or "") not in COUNTED_QUERY_PATHS:
        return None
    pair = await metered(org_id, entitlement)
    if pair is None:
        return None
    _, card = pair

    if is_service_identity(getattr(execution, "user_id", None)):
        credits, reason = 0, REASON_SERVICE
    else:
        credits, reason = query_outcome(execution, card.query_credits)

    ref_type, ref_id = _ref(execution)
    occurred_at = getattr(execution, "terminal_at", None) or datetime.now(UTC)
    payload = json_safe_payload(
        {
            "execution_id": str(execution.id),
            "run_id": getattr(execution, "run_id", None),
            "conversation_id": getattr(execution, "conversation_id", None),
            "connection_name": getattr(execution, "connection_name", None),
            "query_path": getattr(execution, "query_path", None),
            "status": getattr(execution, "status", None),
            "error_code": getattr(execution, "public_error_code", None),
            "row_count": getattr(execution, "row_count", None),
        }
    )
    entry = LedgerEntry(
        org_id=org_id,
        entry_type="consume",
        credits=credits,
        unit="query",
        quantity=1,
        reason=reason,
        source=source or derive_source(execution),
        idempotency_key=f"query:{execution.id}",
        occurred_at=occurred_at,
        ref_type=ref_type,
        ref_id=ref_id,
        user_id=getattr(execution, "user_id", None),
        payload=payload,
    )
    return await write_in_savepoint(session, entry)


__all__ = [
    "COUNTED_QUERY_PATHS",
    "EVAL_RUNNER_USER_ID",
    "WAREHOUSE_EXECUTED_ERROR_CODES",
    "derive_source",
    "emit_query_credit",
    "query_outcome",
]
