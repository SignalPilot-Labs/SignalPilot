"""Deterministic size-aware routing for governed chat queries."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select

from gateway.connectors.pool_manager import pool_manager
from gateway.db.models import GatewayChatConversation, GatewayQueryPlan
from gateway.engine import sqlglot_dialect, validate_sql
from gateway.governance.annotations import load_annotations
from gateway.governance.cost_estimator import CostEstimate, CostEstimator
from gateway.governance.query_executor import GovernedQueryContext, normalize_sql
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.store import Store
from gateway.store import standalone_chat as chat_store

MCP_MAX_ROWS = 10_000
TRACK_A_MAX_ROWS = 100_000
MAX_RESULT_BYTES = 10 * 1024 * 1024
UNKNOWN_SCOUT_ROWS = 1_000
PLAN_POLICY_VERSION = "hybrid-chat-router-v1"

QueryRoute = Literal["mcp", "notebook_sdk", "dataset_ref", "aggregate_required", "refuse"]
ExecutionNeed = Literal["sql", "python"]


class QueryPlanError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class QueryPlanDecision:
    plan_id: str
    sql_hash: str
    estimated_scan_rows: int | None
    estimated_scan_bytes: int | None
    estimated_output_rows: int | None
    estimated_output_bytes: int | None
    estimated_cost_usd: float
    estimate_quality: Literal["exact", "approximate", "unknown"]
    route: QueryRoute
    route_reason: str
    approval_required: bool
    expires_at: datetime
    scout_row_limit: int | None = None
    shadow: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "sql_hash": self.sql_hash,
            "estimated_scan_rows": self.estimated_scan_rows,
            "estimated_scan_bytes": self.estimated_scan_bytes,
            "estimated_output_rows": self.estimated_output_rows,
            "estimated_output_bytes": self.estimated_output_bytes,
            "estimated_cost_usd": self.estimated_cost_usd,
            "estimate_quality": self.estimate_quality,
            "route": self.route,
            "route_reason": self.route_reason,
            "approval_required": self.approval_required,
            "expires_at": self.expires_at,
            "scout_row_limit": self.scout_row_limit,
            "shadow": self.shadow,
        }


def _dataset_connectors() -> set[str]:
    raw = os.getenv("SP_CHAT_DATASET_CONNECTORS", "postgres,snowflake")
    return {value.strip().lower() for value in raw.split(",") if value.strip()}


def _policy_hash(*, db_type: str, blocked_tables: list[str]) -> str:
    flags = enterprise_chat_feature_flags()
    policy = {
        "version": PLAN_POLICY_VERSION,
        "mcp_max_rows": MCP_MAX_ROWS,
        "track_a_max_rows": TRACK_A_MAX_ROWS,
        "max_result_bytes": MAX_RESULT_BYTES,
        "unknown_scout_rows": UNKNOWN_SCOUT_ROWS,
        "size_router": flags.size_router,
        "size_router_shadow": flags.size_router_shadow,
        "query_approval": flags.query_approval,
        "notebook_analysis": flags.notebook_analysis,
        "dataset_refs": flags.dataset_refs,
        "dataset_connectors": sorted(_dataset_connectors()),
        "db_type": db_type,
        "blocked_tables": sorted(blocked_tables),
    }
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode("utf-8")).hexdigest()


def _raw_export_requested(sql: str, purpose: str) -> bool:
    intent = purpose.lower()
    export_markers = ("raw export", "export every", "download all", "all raw rows", "data dump")
    if any(marker in intent for marker in export_markers):
        return True
    normalized = re.sub(r"\s+", " ", sql.strip().lower())
    return bool(re.search(r"\bselect\s+\*\s+from\b", normalized)) and not re.search(
        r"\b(limit\s+\d+|group\s+by|count\s*\(|sum\s*\(|avg\s*\(|min\s*\(|max\s*\()",
        normalized,
    )


def choose_query_route(
    *,
    execution_need: ExecutionNeed,
    estimated_output_rows: int | None,
    estimated_output_bytes: int | None,
    estimate_quality: str,
    track_b_enabled: bool,
    connector_supports_datasets: bool,
    row_level_analysis_justified: bool,
    raw_export_requested: bool,
    notebook_analysis_enabled: bool = True,
) -> tuple[QueryRoute, str, int | None]:
    """Return the locked route; scan volume deliberately does not participate."""
    if raw_export_requested:
        return "refuse", "Raw exports are not permitted by the chat runtime policy.", None
    if estimated_output_rows is None or estimated_output_bytes is None or estimate_quality == "unknown":
        return (
            "mcp",
            "Output cardinality is unknown; only a 1,000-row scouting query is permitted before a bounded aggregate.",
            UNKNOWN_SCOUT_ROWS,
        )

    oversized = estimated_output_rows > TRACK_A_MAX_ROWS or estimated_output_bytes > MAX_RESULT_BYTES
    if oversized:
        if (
            notebook_analysis_enabled
            and track_b_enabled
            and connector_supports_datasets
            and row_level_analysis_justified
        ):
            return (
                "dataset_ref",
                "The justified row-level working set exceeds Track A and will stream to DatasetRef.",
                None,
            )
        return (
            "aggregate_required",
            "The predicted output exceeds 100,000 rows or 10 MiB and must be reduced in warehouse SQL.",
            None,
        )
    if execution_need == "python" or estimated_output_rows > MCP_MAX_ROWS:
        if not notebook_analysis_enabled:
            return (
                "aggregate_required",
                "Notebook analysis is disabled; rewrite the work as a bounded warehouse aggregate.",
                None,
            )
        return "notebook_sdk", "Bounded Python or more-than-10,000-row analysis requires the notebook SDK.", None
    return "mcp", "The complete predicted result fits the MCP row and byte limits.", None


def _explicit_row_limit(sql: str, dialect: str | None) -> int | None:
    """Literal top-level row bound (LIMIT n / TOP n / FETCH NEXT n ROWS), if any.

    An explicit bound caps the true output cardinality no matter what the
    engine's plan-level cardinality guess says, so the router must never
    predict more output rows than this.
    """
    try:
        import sqlglot

        expression = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    if expression is None:
        return None
    node = expression.args.get("limit")
    if node is None:
        return None
    literal = node.args.get("expression") or node.args.get("count")
    try:
        value = int(literal.this)
    except (AttributeError, TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _estimate_quality(estimate: CostEstimate) -> Literal["exact", "approximate", "unknown"]:
    if estimate.quality == "exact":
        return "exact"
    if estimate.estimated_output_rows is None:
        return "unknown"
    return "approximate"


def _bounded_output_bytes(estimate: CostEstimate) -> int | None:
    if estimate.estimated_output_bytes is not None:
        return max(0, estimate.estimated_output_bytes)
    if estimate.estimated_output_rows is not None:
        # EXPLAIN adapters without width metadata still get a conservative,
        # deterministic byte estimate rather than silently ignoring the byte cap.
        return max(0, estimate.estimated_output_rows) * 512
    return None


async def _approval_required(store: Store, context: GovernedQueryContext, estimated_cost_usd: float) -> bool:
    if not enterprise_chat_feature_flags().query_approval:
        return False
    if not context.conversation_id:
        return False
    conversation = await store.session.scalar(
        select(GatewayChatConversation).where(
            GatewayChatConversation.id == context.conversation_id,
            GatewayChatConversation.org_id == store._require_org_id(),
            GatewayChatConversation.user_id == (store.user_id or "local"),
        )
    )
    if conversation is None:
        return True
    remaining = max(
        0.0,
        conversation.chat_budget_usd - conversation.actual_spend_usd - conversation.reserved_spend_usd,
    )
    return estimated_cost_usd > conversation.per_query_budget_usd or estimated_cost_usd > remaining


async def create_query_plan(
    store: Store,
    *,
    connection_name: str,
    sql: str,
    purpose: str,
    execution_need: ExecutionNeed,
    context: GovernedQueryContext,
    row_level_analysis_justified: bool = False,
) -> QueryPlanDecision:
    info = await store.get_connection(connection_name)
    if info is None:
        raise QueryPlanError("connection_not_found", "Connection not found")
    if context.run_id and not all(
        (context.conversation_id, context.project_id, context.commit_sha, context.branch)
    ):
        raise QueryPlanError("scope_incomplete", "Chat plans require run, project, branch, commit, and conversation scope")

    settings = await store.load_settings()
    annotations = load_annotations(store._require_org_id(), connection_name)
    blocked_tables = list(annotations.blocked_tables)
    blocked_tables.extend(table for table in settings.blocked_tables or [] if table not in blocked_tables)
    dialect = sqlglot_dialect(info.db_type)
    validation = validate_sql(sql, blocked_tables=blocked_tables or None, dialect=dialect)
    normalized_sql = normalize_sql(sql, dialect)
    sql_hash = hashlib.sha256(normalized_sql.encode("utf-8")).hexdigest()
    policy_hash = _policy_hash(db_type=info.db_type, blocked_tables=blocked_tables)
    expires_at = datetime.now(UTC) + timedelta(minutes=15)

    estimate = CostEstimate(warning="Query is unsafe")
    if validation.ok:
        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            raise QueryPlanError("credentials_missing", "No credentials stored for this connection")
        extras = await store.get_credential_extras(connection_name)
        async with pool_manager.connection(
            info.db_type,
            conn_str,
            credential_extras=extras,
            connection_name=connection_name,
        ) as connector:
            estimate = await CostEstimator.estimate(connector, sql, info.db_type)

    if validation.ok:
        explicit_limit = _explicit_row_limit(sql, dialect)
        if explicit_limit is not None and (
            estimate.estimated_output_rows is None
            or estimate.estimated_output_rows > explicit_limit
        ):
            estimate.estimated_output_rows = explicit_limit
            # The byte estimate was derived from the uncapped row guess; let
            # _bounded_output_bytes recompute it from the capped rows.
            estimate.estimated_output_bytes = None

    quality = _estimate_quality(estimate)
    output_bytes = _bounded_output_bytes(estimate)
    if not validation.ok:
        route: QueryRoute = "refuse"
        route_reason = validation.blocked_reason or "The query is unsafe."
        scout_limit = None
    else:
        flags = enterprise_chat_feature_flags()
        route, route_reason, scout_limit = choose_query_route(
            execution_need=execution_need,
            estimated_output_rows=estimate.estimated_output_rows,
            estimated_output_bytes=output_bytes,
            estimate_quality=quality,
            track_b_enabled=flags.dataset_refs,
            connector_supports_datasets=info.db_type in _dataset_connectors(),
            row_level_analysis_justified=row_level_analysis_justified,
            raw_export_requested=_raw_export_requested(sql, purpose),
            notebook_analysis_enabled=flags.notebook_analysis,
        )
    approval_required = await _approval_required(store, context, max(0.0, estimate.estimated_usd))
    plan_id = str(uuid.uuid4())
    shadow = bool(context.run_id and not enterprise_chat_feature_flags().size_router)
    shadow_route: str | None = None
    shadow_reason: str | None = None
    if shadow and validation.ok:
        # Size routing is DISABLED (SP_FEATURE_CHAT_SIZE_ROUTER unset). The
        # would-be decision is recorded for telemetry only; the surfaced route
        # must never block the agent, otherwise "shadow" mode still gates.
        permissive: QueryRoute = "notebook_sdk" if execution_need == "python" else "mcp"
        if route != permissive or scout_limit is not None:
            shadow_route, shadow_reason = route, route_reason
            route = permissive
            route_reason = "Size routing is disabled; the planned query is approved for execution."
            scout_limit = None
    row = GatewayQueryPlan(
        id=plan_id,
        org_id=store._require_org_id(),
        user_id=store.user_id,
        conversation_id=context.conversation_id,
        run_id=context.run_id,
        project_id=context.project_id,
        commit_sha=context.commit_sha,
        branch=context.branch,
        connection_name=connection_name,
        purpose=purpose,
        execution_need=execution_need,
        normalized_sql=normalized_sql,
        sql_hash=sql_hash,
        estimated_scan_rows=estimate.estimated_scan_rows,
        estimated_scan_bytes=estimate.estimated_scan_bytes,
        estimated_output_rows=estimate.estimated_output_rows,
        estimated_output_bytes=output_bytes,
        estimated_cost_usd=max(0.0, estimate.estimated_usd),
        estimate_quality=quality,
        route=route,
        route_reason=route_reason,
        approval_required=approval_required,
        policy_version=PLAN_POLICY_VERSION,
        policy_hash=policy_hash,
        shadow=shadow,
        scout_row_limit=scout_limit,
        expires_at=expires_at,
    )
    store.session.add(row)
    await store.session.commit()
    if context.run_id:
        await chat_store.append_event(
            store.session,
            run_id=context.run_id,
            event_type="plan_created",
            payload={
                "plan_id": plan_id,
                "sql_hash": sql_hash,
                "estimate_quality": quality,
                "shadow": shadow,
                # Chat-visible context: what the agent wanted and the SQL it
                # planned. The same user already sees raw SQL via `sql` events.
                "purpose": (purpose or "")[:300],
                "sql": (sql or "")[:4000],
                "estimated_output_rows": estimate.estimated_output_rows,
                "estimated_cost_usd": round(max(0.0, estimate.estimated_usd or 0.0), 6),
            },
        )
        await chat_store.append_event(
            store.session,
            run_id=context.run_id,
            event_type="route_selected",
            payload={
                "plan_id": plan_id,
                "route": route,
                "route_reason": route_reason,
                **(
                    {"shadow_route": shadow_route, "shadow_reason": shadow_reason}
                    if shadow_route
                    else {}
                ),
            },
        )
    return QueryPlanDecision(
        plan_id=plan_id,
        sql_hash=sql_hash,
        estimated_scan_rows=estimate.estimated_scan_rows,
        estimated_scan_bytes=estimate.estimated_scan_bytes,
        estimated_output_rows=estimate.estimated_output_rows,
        estimated_output_bytes=output_bytes,
        estimated_cost_usd=max(0.0, estimate.estimated_usd),
        estimate_quality=quality,
        route=route,
        route_reason=route_reason,
        approval_required=approval_required,
        expires_at=expires_at,
        scout_row_limit=scout_limit,
        shadow=shadow,
    )


async def require_execution_plan(
    store: Store,
    *,
    plan_id: str,
    sql: str,
    connection_name: str,
    context: GovernedQueryContext,
    allowed_routes: set[str],
) -> GatewayQueryPlan:
    plan = await store.session.get(GatewayQueryPlan, plan_id)
    if plan is None or plan.org_id != store._require_org_id() or plan.user_id != store.user_id:
        raise QueryPlanError("plan_not_found", "Query plan not found")
    if plan.expires_at <= datetime.now(UTC):
        raise QueryPlanError("plan_expired", "Query plan expired; create a fresh plan")
    info = await store.get_connection(connection_name)
    if info is None:
        raise QueryPlanError("connection_not_found", "Connection not found")
    settings = await store.load_settings()
    annotations = load_annotations(store._require_org_id(), connection_name)
    blocked_tables = list(annotations.blocked_tables)
    blocked_tables.extend(table for table in settings.blocked_tables or [] if table not in blocked_tables)
    dialect = sqlglot_dialect(info.db_type)
    sql_hash = hashlib.sha256(normalize_sql(sql, dialect).encode("utf-8")).hexdigest()
    scope_matches = (
        plan.sql_hash == sql_hash
        and plan.connection_name == connection_name
        and plan.run_id == context.run_id
        and plan.conversation_id == context.conversation_id
        and plan.project_id == context.project_id
        and plan.commit_sha == context.commit_sha
        and plan.branch == context.branch
    )
    if not scope_matches:
        raise QueryPlanError("plan_scope_mismatch", "Query plan does not match SQL or execution scope")
    if plan.policy_hash != _policy_hash(db_type=info.db_type, blocked_tables=blocked_tables):
        raise QueryPlanError("plan_policy_changed", "Query policy changed; create a fresh plan")
    if plan.route not in allowed_routes:
        raise QueryPlanError("route_mismatch", f"Plan route is {plan.route}, not an allowed execution route")
    return plan
