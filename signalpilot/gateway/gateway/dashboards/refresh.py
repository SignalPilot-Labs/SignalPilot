"""Refresh execution.

SQL mode re-runs every dataset ``source`` through the governed query
executor and writes the rows as CSV. Agent mode seeds a chat run that
reproduces the datasets; the scheduler finalizes it when the run ends.

Both modes assemble a ``VersionMaterial``, run the chart checks against the
new rows, and only then create a version and swap ``current_version_id``.
A refresh fails, and the live version stays, when any SQL dataset errored,
any chart would fail, or a dataset that had rows is now empty.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayChatRun,
    GatewayDashboardRefresh,
    GatewayPublishedDashboard,
    GatewayPublishedDashboardVersion,
)
from gateway.governance.context import current_org_id_var
from gateway.governance.query_executor import GovernedQueryContext, GovernedQueryError
from gateway.store import Store

from . import schema, store
from .checks import SpecCheck, check_spec
from .datasets import (
    Row,
    inline_rows,
    parse_dataset_bytes,
    resolve_file_ref,
    result_columns,
    rows_to_csv,
    rows_to_json,
)
from .service import (
    DatasetPayload,
    VersionMaterial,
    dashboard_artifact_path,
    render_prompt,
    seed_dashboard_chat,
    write_version,
)
from .storage import MAX_DATASET_BYTES, MAX_SPEC_BYTES, DashboardStorage, dashboard_storage

logger = logging.getLogger(__name__)

SQL_ROW_LIMIT = 50_000
SQL_TIMEOUT_SECONDS = 120
REFRESH_CHAT_ORIGIN = "dashboard_refresh"
REFRESH_CHAT_BUDGET_USD = 2.0
REFRESH_PER_QUERY_BUDGET_USD = 0.25


class QueryExecutor(Protocol):
    async def execute(
        self,
        store: Store,
        *,
        connection_name: str,
        sql: str,
        row_limit: int,
        timeout_seconds: int,
        context: GovernedQueryContext,
    ) -> Any: ...


def _default_executor() -> QueryExecutor:
    from gateway.governance.query_executor import GovernedQueryExecutor

    return GovernedQueryExecutor()


def refresh_identity(dashboard: GatewayPublishedDashboard) -> str:
    return f"dashboard-refresh:{dashboard.id}"


# ── Outcome assembly ────────────────────────────────────────────────────────


class RefreshOutcome:
    """Per-dataset results, the assembled material, and the rows for checks."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self.material = VersionMaterial(spec=spec)
        self.rows: dict[str, list[Row] | None] = {}
        self.datasets: dict[str, dict[str, Any]] = {}
        self.check: SpecCheck | None = None

    def inline(self, name: str, rows: list[Row]) -> None:
        self.rows[name] = rows
        self.datasets[name] = {"status": "inline", "row_count": len(rows)}

    def refreshed(self, name: str, payload: DatasetPayload, *, previous_rows: int) -> None:
        self.material.payloads[name] = payload
        self.rows[name] = payload.rows
        if previous_rows > 0 and not payload.rows:
            self.failed(name, f"Query returned no rows; the previous version had {previous_rows}", row_count=0)
            return
        self.datasets[name] = {"status": "refreshed", "row_count": len(payload.rows)}

    def carried(self, name: str, key: str, meta: dict[str, Any], rows: list[Row] | None) -> None:
        self.material.carried[name] = (key, meta)
        self.rows[name] = rows
        self.datasets[name] = {"status": "carried", "row_count": int(meta.get("row_count") or 0)}

    def failed(self, name: str, error: str, *, row_count: int | None = None) -> None:
        self.rows.setdefault(name, None)
        entry: dict[str, Any] = {"status": "failed", "error": error[:2000]}
        if row_count is not None:
            entry["row_count"] = row_count
        self.datasets[name] = entry

    @property
    def failed_datasets(self) -> list[str]:
        return [name for name, entry in self.datasets.items() if entry.get("status") == "failed"]

    def run_checks(self) -> None:
        self.check = check_spec(self.material.spec, self.rows)

    @property
    def errors(self) -> list[str]:
        """Dataset failures first; chart failures only for datasets that loaded."""
        failed = self.failed_datasets
        messages = [f"{name}: {self.datasets[name]['error']}" for name in failed]
        if self.check is not None:
            messages.extend(self.check.failure_messages(except_datasets=failed))
        return messages

    def detail(self) -> dict[str, Any]:
        return {
            "datasets": self.datasets,
            "charts": self.check.as_detail() if self.check is not None else [],
        }


async def carry_previous(
    storage: DashboardStorage,
    outcome: RefreshOutcome,
    version: GatewayPublishedDashboardVersion,
    name: str,
    filename: str,
) -> None:
    """Reference the previous version's object for a dataset with no source."""
    key = (version.dataset_keys or {}).get(name)
    meta = (version.dataset_meta or {}).get(name) or {}
    if not key:
        outcome.failed(name, "No stored file in the previous version")
        return
    try:
        rows = parse_dataset_bytes(await storage.get_dataset(key), filename)
    except Exception as exc:
        outcome.failed(name, f"Stored file is unreadable: {exc}")
        return
    outcome.carried(name, key, meta, rows)


def previous_row_count(version: GatewayPublishedDashboardVersion, name: str) -> int:
    meta = (version.dataset_meta or {}).get(name) or {}
    return int(meta.get("row_count") or 0)


# ── SQL mode ────────────────────────────────────────────────────────────────


async def run_sql_datasets(
    db: AsyncSession,
    storage: DashboardStorage,
    executor: QueryExecutor,
    dashboard: GatewayPublishedDashboard,
    version: GatewayPublishedDashboardVersion,
    spec: dict[str, Any],
) -> RefreshOutcome:
    outcome = RefreshOutcome(spec)
    sources = schema.dataset_sources(spec)
    query_store = Store(db, org_id=dashboard.org_id, user_id=refresh_identity(dashboard))
    context = GovernedQueryContext(path="dashboard", project_id=dashboard.project_id)
    for name, definition in schema.dataset_definitions(spec).items():
        rows = inline_rows(definition)
        if rows is not None:
            outcome.inline(name, rows)
            continue
        filename = str(definition.get("file") or f"{name}.csv")
        source = sources.get(name)
        if source is None:
            await carry_previous(storage, outcome, version, name, filename)
            continue
        connection = str(source.get("connection") or "").strip()
        sql = str(source.get("sql") or "").strip()
        if not connection or not sql:
            outcome.failed(name, "Source has no connection or no sql")
            continue
        try:
            result = await asyncio.wait_for(
                executor.execute(
                    query_store,
                    connection_name=connection,
                    sql=sql,
                    row_limit=SQL_ROW_LIMIT,
                    timeout_seconds=SQL_TIMEOUT_SECONDS,
                    context=context,
                ),
                timeout=SQL_TIMEOUT_SECONDS + 30,
            )
        except GovernedQueryError as exc:
            outcome.failed(name, f"{exc.code}: {exc}")
            continue
        except TimeoutError:
            outcome.failed(name, f"Query timed out after {SQL_TIMEOUT_SECONDS}s")
            continue
        except Exception as exc:
            outcome.failed(name, f"Query failed: {exc}")
            continue
        result_rows = list(result.rows or [])
        columns = result_columns(getattr(result, "columns", None), result_rows)
        data = rows_to_json(result_rows) if filename.lower().endswith(".json") else rows_to_csv(columns, result_rows)
        payload = DatasetPayload(data=data, filename=filename.rsplit("/", 1)[-1], rows=parse_dataset_bytes(data, filename))
        outcome.refreshed(name, payload, previous_rows=previous_row_count(version, name))
    return outcome


# ── Agent mode ──────────────────────────────────────────────────────────────


def refresh_message(dashboard: GatewayPublishedDashboard, spec: dict[str, Any]) -> str:
    sources = schema.dataset_sources(spec)
    refs = schema.dataset_file_refs(spec)
    listed = [f"- `{name}` -> `{refs.get(name, '?')}` on connection `{source.get('connection') or '?'}`" for name, source in sources.items()]
    return render_prompt(
        "refresh_prompt.md",
        {
            "dashboard_name": dashboard.name,
            "dashboard_path": dashboard_artifact_path(dashboard),
            "dataset_list": "\n".join(listed) or "- (none)",
            "spec_json": json.dumps(spec, indent=2, ensure_ascii=False),
        },
    )


async def seed_agent_run(
    db: AsyncSession,
    dashboard: GatewayPublishedDashboard,
    spec: dict[str, Any],
) -> tuple[str, str]:
    """Create the refresh conversation and its queued run. Returns (conversation_id, run_id)."""
    return await seed_dashboard_chat(
        db,
        dashboard,
        user_id=dashboard.created_by_user_id,
        message=refresh_message(dashboard, spec),
        title=f"Dashboard refresh: {dashboard.name}",
        origin=REFRESH_CHAT_ORIGIN,
        chat_budget_usd=REFRESH_CHAT_BUDGET_USD,
        per_query_budget_usd=REFRESH_PER_QUERY_BUDGET_USD,
    )


async def collect_agent_outcome(
    db: AsyncSession,
    storage: DashboardStorage,
    dashboard: GatewayPublishedDashboard,
    version: GatewayPublishedDashboardVersion,
    refresh: GatewayDashboardRefresh,
    run: GatewayChatRun,
) -> RefreshOutcome | str:
    """Assemble the outcome from files the run wrote, or return an error string."""
    from gateway.store.standalone_chat import list_conversation_files

    if run.status != "completed":
        reason = run.public_error_message or run.public_error_code or run.status
        return f"Agent run ended with status {run.status}: {reason}"
    manifest = [
        row
        for row in await list_conversation_files(
            db,
            org_id=dashboard.org_id,
            user_id=dashboard.created_by_user_id,
            conversation_id=refresh.conversation_id or "",
        )
        if row.origin_run_id == run.id
    ]
    previous_spec = await storage.get_spec(version.spec_key)
    spec_row = resolve_file_ref(dashboard_artifact_path(dashboard), manifest)
    if spec_row is None:
        return f"The agent run did not write {dashboard_artifact_path(dashboard)}"
    spec, errors = schema.parse_spec(await storage.get_chat_object(spec_row.object_key, max_bytes=MAX_SPEC_BYTES))
    if spec is None:
        return "The agent run wrote an invalid dashboard spec: " + "; ".join(errors)
    previous_ids = [chart.get("id") for chart in previous_spec.get("charts") or []]
    new_ids = [chart.get("id") for chart in spec.get("charts") or []]
    if previous_ids != new_ids or set(schema.dataset_definitions(previous_spec)) != set(schema.dataset_definitions(spec)):
        return "The agent run changed chart ids or dataset names; the spec must stay unchanged"
    outcome = RefreshOutcome(spec)
    sources = schema.dataset_sources(spec)
    for name, definition in schema.dataset_definitions(spec).items():
        rows = inline_rows(definition)
        if rows is not None:
            outcome.inline(name, rows)
            continue
        filename = str(definition.get("file") or f"{name}.csv")
        if name not in sources:
            await carry_previous(storage, outcome, version, name, filename)
            continue
        file_row = resolve_file_ref(filename, manifest)
        if file_row is None:
            outcome.failed(name, f"The agent run did not write {filename}")
            continue
        data = await storage.get_chat_object(file_row.object_key, max_bytes=MAX_DATASET_BYTES)
        try:
            parsed = parse_dataset_bytes(data, filename)
        except ValueError as exc:
            outcome.failed(name, f"Dataset file could not be parsed: {exc}")
            continue
        payload = DatasetPayload(data=data, filename=filename.rsplit("/", 1)[-1], rows=parsed)
        outcome.refreshed(name, payload, previous_rows=previous_row_count(version, name))
    return outcome


# ── Finishing ───────────────────────────────────────────────────────────────


def notify_failure(dashboard: GatewayPublishedDashboard, refresh: GatewayDashboardRefresh) -> dict[str, Any]:
    """Record the failure. There is no email or Slack channel for system
    failures in the gateway yet, so the channel is the application log."""
    logger.warning(
        "Dashboard refresh failed: dashboard=%s (%s) refresh=%s mode=%s trigger=%s error=%s",
        dashboard.id,
        dashboard.name,
        refresh.id,
        refresh.mode,
        refresh.trigger,
        refresh.error,
    )
    return {"channel": "log", "at": datetime.now(UTC).isoformat()}


async def fail_refresh(
    db: AsyncSession,
    dashboard: GatewayPublishedDashboard,
    refresh: GatewayDashboardRefresh,
    error: str,
    detail: dict[str, Any] | None = None,
) -> bool:
    """Write the failure. Returns False, and writes nothing, when the row is
    no longer in progress (another writer, such as the stale sweep, settled it)."""
    refresh_id = refresh.id
    if not await store.settle_refresh(db, refresh_id, "failed"):
        await db.rollback()  # expires the rows; only the captured id is safe to read
        logger.warning("Dashboard refresh %s was already settled; failure not recorded: %s", refresh_id, error)
        return False
    now = store.utcnow()
    refresh.status = "failed"
    refresh.error = error[:4000]
    refresh.finished_at = now
    refresh.detail = dict(detail or {})
    dashboard.last_refresh_at = now
    dashboard.last_refresh_status = "failed"
    dashboard.updated_at = now
    if dashboard.notify_on_failure:
        refresh.detail["notification"] = notify_failure(dashboard, refresh)
    await db.commit()
    return True


async def finish_refresh(
    db: AsyncSession,
    storage: DashboardStorage,
    dashboard: GatewayPublishedDashboard,
    refresh: GatewayDashboardRefresh,
    outcome: RefreshOutcome,
) -> bool:
    """Validate, then either create the version and swap or fail.

    On success the version row, the ``current_version_id`` swap, the refresh
    status, and the dashboard's ``last_refresh_*`` land in one commit: a reader
    never sees a new live version whose refresh is still "running".

    The status write is a compare-and-set from an in-progress status. A late
    finisher, one whose row the stale sweep already failed, loses it: the
    version row and the swap are rolled back before anything is visible and
    the call returns False. Its uploaded objects stay under the dashboard
    prefix, harmless until the dashboard is deleted.
    """
    outcome.run_checks()
    errors = outcome.errors
    if errors:
        return await fail_refresh(db, dashboard, refresh, "; ".join(errors), outcome.detail())
    refresh_id = refresh.id
    version = await write_version(db, storage, dashboard, outcome.material, produced_by="refresh", producer_ref=refresh_id)
    version_id = version.id
    if not await store.settle_refresh(db, refresh_id, "succeeded"):
        await db.rollback()  # drops the version row and the swap; expires the rows
        logger.warning("Dashboard refresh %s was already settled; discarding version %s", refresh_id, version_id)
        return False
    now = store.utcnow()
    refresh.status = "succeeded"
    refresh.version_id = version.id
    refresh.finished_at = now
    refresh.detail = outcome.detail()
    dashboard.last_refresh_at = now
    dashboard.last_refresh_status = "succeeded"
    dashboard.updated_at = now
    await db.commit()
    return True


# ── Entry points ────────────────────────────────────────────────────────────


async def run_refresh(
    session_factory: Callable[[], AsyncSession],
    refresh_id: str,
    *,
    storage: DashboardStorage | None = None,
    executor: QueryExecutor | None = None,
) -> None:
    """Execute one queued refresh to completion (sql) or to running (agent)."""
    storage = storage or dashboard_storage()
    async with session_factory() as db:
        refresh = await store.get_refresh(db, refresh_id)
        if refresh is None or refresh.status != "queued":
            return
        dashboard = await store.get_dashboard_by_id(db, refresh.dashboard_id)
        if dashboard is None:
            return
        dashboard_id = dashboard.id
        token = current_org_id_var.set(dashboard.org_id)
        try:
            refresh.status = "running"
            refresh.started_at = store.utcnow()
            await db.commit()
            version = await store.current_version(db, dashboard)
            if version is None:
                await fail_refresh(db, dashboard, refresh, "Dashboard has no current version")
                return
            spec = await storage.get_spec(version.spec_key)
            if refresh.mode == "agent":
                refresh.conversation_id, refresh.run_id = await seed_agent_run(db, dashboard, spec)
                await db.commit()
                return
            # The stale sweep sizes its budget by this count.
            refresh.detail = {"sql_datasets": len(schema.dataset_sources(spec))}
            await db.commit()
            outcome = await run_sql_datasets(db, storage, executor or _default_executor(), dashboard, version, spec)
            await finish_refresh(db, storage, dashboard, refresh, outcome)
        except Exception as exc:
            logger.exception("Dashboard refresh %s crashed", refresh_id)
            await db.rollback()
            # The rollback expired every loaded row; reload before writing the
            # failure so the refresh cannot stay "running" forever.
            refresh = await store.get_refresh(db, refresh_id)
            dashboard = await store.get_dashboard_by_id(db, dashboard_id)
            if refresh is not None and dashboard is not None:
                await fail_refresh(db, dashboard, refresh, f"Refresh crashed: {exc}")
        finally:
            current_org_id_var.reset(token)


async def finalize_agent_refresh(
    db: AsyncSession,
    refresh: GatewayDashboardRefresh,
    run: GatewayChatRun,
    *,
    storage: DashboardStorage | None = None,
) -> None:
    """Turn a terminal agent run into a version or a failure."""
    storage = storage or dashboard_storage()
    dashboard = await store.get_dashboard_by_id(db, refresh.dashboard_id)
    if dashboard is None:
        return
    version = await store.current_version(db, dashboard)
    if version is None:
        await fail_refresh(db, dashboard, refresh, "Dashboard has no current version")
        return
    try:
        outcome = await collect_agent_outcome(db, storage, dashboard, version, refresh, run)
    except Exception as exc:
        logger.exception("Dashboard refresh %s finalize crashed", refresh.id)
        await fail_refresh(db, dashboard, refresh, f"Finalize crashed: {exc}")
        return
    if isinstance(outcome, str):
        await fail_refresh(db, dashboard, refresh, outcome)
        return
    await finish_refresh(db, storage, dashboard, refresh, outcome)
