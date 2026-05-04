"""Audit hook for the dbt-proxy.

Every statement that enters the Execute/SimpleQuery path calls record() exactly
once, regardless of statement kind, blocking decision, or outcome. This includes
dbt-emitted BEGIN, COMMIT, introspection probes, DDL, and DML.

Volume note: audit rows are written synchronously per statement. For high-
throughput dbt runs (100s of compiled models), this can generate O(100) rows
per run. TODO(R8): switch to batched/sampled audit writes to reduce DB pressure.
"""

from __future__ import annotations

import logging
import time
import uuid

from ..models import AuditEntry
from ..store import Store
from .tokens import RunTokenClaims

logger = logging.getLogger(__name__)


class AuditWriteError(Exception):
    """Raised when the audit row cannot be persisted.

    Per spec §A.10: audit is a hard precondition. If the write fails, the
    statement must be aborted (the caller returns ErrorResponse to the client).
    """


async def record(
    claims: RunTokenClaims,
    sql: str,
    *,
    blocked: bool,
    block_reason: str | None,
    kind: str,
    store: Store,
) -> None:
    """Append one AuditEntry for a proxy-forwarded statement.

    Called exactly once per forwarded statement — no filters. If the audit
    write fails, AuditWriteError is raised. The caller MUST return an
    ErrorResponse to the client rather than executing un-audited SQL.
    """
    entry = AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        event_type="dbt_proxy",
        connection_name=claims.connector_name,
        sql=sql,
        blocked=blocked,
        block_reason=block_reason,
        metadata={
            "run_id": str(claims.run_id),
            "org_id": claims.org_id,
            "user_id": claims.user_id,
            "kind": kind,
        },
    )
    try:
        await store.append_audit(entry)
    except Exception as exc:
        # Log separately so the audit-failure record itself is visible.
        logger.error(
            "dbt_proxy audit write FAILED run_id=%s entry_id=%s exc=%r — aborting statement",
            claims.run_id,
            entry.id,
            exc,
        )
        raise AuditWriteError(f"audit write failed (ref={entry.id})") from exc


__all__ = ["AuditWriteError", "record"]
