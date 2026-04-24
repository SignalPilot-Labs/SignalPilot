"""Governance context variable — current org scope for per-request isolation.

Sets the org_id for all governance singletons (budget, query_cache, schema_cache)
within a request or MCP tool call. Background tasks that cross org boundaries must
set and reset this variable explicitly per-iteration (see main.py schema refresh loop).
"""

from __future__ import annotations

import contextvars

current_org_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "governance_current_org_id", default=None
)


def require_org_id() -> str:
    """Return the current org_id or raise if the governance context is not set.

    Fails fast — never returns a default. Callers (Store.__init__, _store_session,
    and main.py's per-iteration set) are responsible for setting the var before any
    governance cache call.
    """
    oid = current_org_id_var.get()
    if not oid:
        raise RuntimeError(
            "governance call requires org_id context — Store/MCP auth did not set current_org_id_var"
        )
    return oid
