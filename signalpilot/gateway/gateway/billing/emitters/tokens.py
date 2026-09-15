"""Model-token emitter: one ledger row per chat run with the agent's cost.

Called from ``store.standalone_chat.worker.record_run_usage`` inside the
transaction that stores ``cost_usd`` / ``usage_json`` on the run row. The
agent SDK reports the run's total cost in USD; credits = round(cost x 100).

Key source (decided in ``standalone_chat.execution.prepare_execution`` and
carried on ``PreparedExecution.key_source``):

``org``          the org's own Anthropic key from org secrets (BYOK)
                 -> ``0`` credits, reason ``byok``
``improvement``  the dedicated improvement-run token: gateway-initiated work
                 -> ``0`` credits, reason ``service_identity``
``platform``     a platform-held key or OAuth token -> ``-round(cost x 100)``
                 reason ``ok``
``none``         no credential resolved (the run cannot have called a model)
                 -> ``0`` credits, reason ``ok``

Payload: the token counts from the usage dict, ``key_source``, ``model`` (when
the usage dict names one; the SDK result does not always), and ``cost_usd``.
Idempotency key ``tokens:chat:{run_id}``: the first usage report for a run
wins, a retried attempt does not double-bill.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..identity import is_service_identity
from ..ledger import LedgerEntry
from ..rates import TOKEN_CREDITS_PER_USD
from ._base import json_safe_payload, metered_entitlement, never_raises, write_in_savepoint

KEY_SOURCE_ORG = "org"
KEY_SOURCE_PLATFORM = "platform"
KEY_SOURCE_IMPROVEMENT = "improvement"
KEY_SOURCE_NONE = "none"
KEY_SOURCES: frozenset[str] = frozenset({KEY_SOURCE_ORG, KEY_SOURCE_PLATFORM, KEY_SOURCE_IMPROVEMENT, KEY_SOURCE_NONE})

REASON_OK = "ok"
REASON_BYOK = "byok"
REASON_SERVICE = "service_identity"

TOKEN_COUNT_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def token_credits(cost_usd: float | None) -> int:
    """Credits for a platform-key run: round half away from zero of cost x 100."""
    if cost_usd is None or cost_usd <= 0:
        return 0
    return int(cost_usd * TOKEN_CREDITS_PER_USD + 0.5)


def usage_counts(usage: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(usage, dict):
        return {}
    counts: dict[str, int] = {}
    for key in TOKEN_COUNT_KEYS:
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            counts[key] = max(0, int(value))
    return counts


def _model_name(usage: dict[str, Any] | None) -> str | None:
    if not isinstance(usage, dict):
        return None
    model = usage.get("model")
    if isinstance(model, str) and model:
        return model
    per_model = usage.get("modelUsage") or usage.get("model_usage")
    if isinstance(per_model, dict) and per_model:
        return ",".join(sorted(str(name) for name in per_model))
    return None


@never_raises
async def emit_token_credit(
    session: AsyncSession,
    run: Any,
    *,
    cost_usd: float | None,
    usage: dict[str, Any] | None,
    key_source: str,
    run_kind: str = "chat",
    entitlement: Any = None,
    now: datetime | None = None,
) -> int | None:
    """Write the token ledger row for ``run`` in ``session``; None when not metered or duplicate."""
    org_id = str(getattr(run, "org_id", "") or "")
    run_id = str(getattr(run, "id", "") or "")
    if not org_id or not run_id:
        return None
    if await metered_entitlement(org_id, entitlement) is None:
        return None
    source_key = key_source if key_source in KEY_SOURCES else KEY_SOURCE_NONE
    if source_key == KEY_SOURCE_ORG:
        credits, reason = 0, REASON_BYOK
    elif source_key == KEY_SOURCE_IMPROVEMENT or is_service_identity(getattr(run, "user_id", None)):
        credits, reason = 0, REASON_SERVICE
    else:
        credits, reason = -token_credits(cost_usd), REASON_OK
    payload = json_safe_payload(
        {
            **usage_counts(usage),
            "key_source": source_key,
            "model": _model_name(usage),
            "cost_usd": round(float(cost_usd), 6) if cost_usd is not None else None,
            "run_kind": run_kind,
        }
    )
    entry = LedgerEntry(
        org_id=org_id,
        entry_type="consume",
        credits=credits,
        unit="tokens",
        quantity=1,
        reason=reason,
        source="chat" if run_kind == "chat" else "system",
        idempotency_key=f"tokens:{run_kind}:{run_id}",
        occurred_at=now or datetime.now(UTC),
        ref_type=f"{run_kind}_run",
        ref_id=run_id,
        user_id=getattr(run, "user_id", None),
        payload=payload,
    )
    return await write_in_savepoint(session, entry)


__all__ = [
    "KEY_SOURCES",
    "KEY_SOURCE_IMPROVEMENT",
    "KEY_SOURCE_NONE",
    "KEY_SOURCE_ORG",
    "KEY_SOURCE_PLATFORM",
    "emit_token_credit",
    "token_credits",
    "usage_counts",
]
