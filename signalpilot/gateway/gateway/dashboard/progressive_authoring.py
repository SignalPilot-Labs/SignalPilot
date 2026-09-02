"""Progressive planner, chart agents, and query-preserving dashboard assembly."""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal

import httpx
from pydantic import Field, model_validator

from gateway.analysis_delivery.model_client import (
    AnthropicMessagesError,
    ClaudeAgentSDKStructuredClient,
    MessagesModelClient,
)
from gateway.dashboard.domain import (
    ChartDefinition,
    ContractModel,
    DashboardDefinition,
    DashboardFieldTarget,
    DashboardFilterRule,
    DashboardFilters,
    DashboardSignalPilot,
    DashboardTileDefinition,
    DashboardTileProperties,
    SemanticChartQuery,
)
from gateway.dashboard.operations import (
    canonicalize_dashboard_filter_targets,
    canonicalize_dashboard_time_series_defaults,
    validate_dashboard_semantics,
    validate_time_series_default_windows,
)
from gateway.models.dashboards import (
    DashboardChartIntent,
    DashboardPlan,
    DashboardProvisionalLayout,
    DashboardSemanticContext,
)

MAX_PHASE_ATTEMPTS = 2
CHART_AGENT_CONCURRENCY = 5


@dataclass(frozen=True)
class ProgressivePhaseResult:
    value: Any
    attempt_count: int
    usage: dict[str, Any]
    latency_ms: float
    throttle_count: int = 0
    throttle_wait_ms: float = 0


class DashboardMergeTile(ContractModel):
    chart_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    section: str = Field(min_length=1, max_length=120)
    order: int = Field(ge=0)
    layout: DashboardProvisionalLayout


class DashboardMergeFilterMapping(ContractModel):
    filter_id: str = Field(min_length=1)
    tile_targets: dict[str, DashboardFieldTarget | Literal[False]]


class DashboardMergeResult(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    tiles: list[DashboardMergeTile] = Field(min_length=1, max_length=30)
    filter_mappings: list[DashboardMergeFilterMapping] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_ids(self) -> DashboardMergeResult:
        chart_ids = [tile.chart_id for tile in self.tiles]
        orders = [tile.order for tile in self.tiles]
        if len(chart_ids) != len(set(chart_ids)):
            raise ValueError("Merge chart IDs must be unique")
        if len(orders) != len(set(orders)):
            raise ValueError("Merge chart order must be unique")
        return self


class ProviderCallGate:
    """Cap chart concurrency and honor the longest observed Retry-After gate."""

    def __init__(self, concurrency: int = CHART_AGENT_CONCURRENCY) -> None:
        self._semaphore = asyncio.Semaphore(concurrency)
        self._lock = asyncio.Lock()
        self._blocked_until = 0.0
        self.throttle_count = 0
        self.throttle_wait_ms = 0.0

    async def _wait_for_provider(self) -> None:
        while True:
            async with self._lock:
                delay = self._blocked_until - time.monotonic()
            if delay <= 0:
                return
            started = time.monotonic()
            await asyncio.sleep(delay)
            async with self._lock:
                self.throttle_wait_ms += (time.monotonic() - started) * 1000

    async def call(self, operation: Callable[[], Any]) -> dict[str, Any]:
        await self._wait_for_provider()
        async with self._semaphore:
            await self._wait_for_provider()
            try:
                return await operation()
            except AnthropicMessagesError as exc:
                retry_delay = _retry_after_seconds(exc.retry_after)
                if retry_delay > 0:
                    async with self._lock:
                        self.throttle_count += 1
                        self._blocked_until = max(
                            self._blocked_until,
                            time.monotonic() + retry_delay,
                        )
                raise


def _retry_after_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(0.0, (parsed - datetime.now(UTC)).total_seconds())


def _tool_input(response: dict[str, Any], tool_name: str) -> Any:
    content = response.get("content")
    if not isinstance(content, list):
        raise ValueError("Dashboard authoring model returned no structured result")
    result = next(
        (
            block.get("input")
            for block in content
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == tool_name
        ),
        None,
    )
    if result is None:
        raise ValueError("Dashboard authoring model returned no structured result")
    return result


def _usage(response: dict[str, Any]) -> dict[str, Any]:
    raw = response.get("usage")
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if key
        in {
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "cost_usd",
        }
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    }


def relevant_explore_projection(
    context: DashboardSemanticContext,
    explore_name: str,
) -> dict[str, Any]:
    explore = next((item for item in context.explores if item.name == explore_name), None)
    if explore is None:
        raise ValueError(f"Unknown explore: {explore_name}")
    return {
        "project_id": context.project_id,
        "commit_sha": context.commit_sha,
        "connection_name": context.connection_name,
        "explore": explore.model_dump(mode="json", exclude_none=True),
    }


class ProgressiveDashboardAuthoringAgent:
    def __init__(
        self,
        *,
        model: str,
        model_client: MessagesModelClient,
        gate: ProviderCallGate | None = None,
    ) -> None:
        self.model = model
        self.chart_model_client = model_client
        if isinstance(model_client, ClaudeAgentSDKStructuredClient):
            # Per-phase contracts are intentionally small enough for native
            # constrained decoding. Planner and merge contracts remain on the
            # proven JSON-contract path used by legacy dashboard authoring.
            self.chart_model_client = ClaudeAgentSDKStructuredClient(
                oauth_token=model_client.oauth_token,
                timeout_seconds=model_client.timeout_seconds,
                use_native_structured_output=True,
                query_runner=model_client._query_runner,
            )
        self.model_client = model_client
        self.gate = gate or ProviderCallGate()

    async def _phase(
        self,
        *,
        tool_name: str,
        description: str,
        system: str,
        payload: dict[str, Any],
        contract: type[ContractModel] | type[DashboardPlan],
        validator: Callable[[Any], None],
        on_attempt: Callable[[int], None] | None = None,
        model_client: MessagesModelClient | None = None,
        repair_model_client: MessagesModelClient | None = None,
    ) -> ProgressivePhaseResult:
        errors: list[str] = []
        total_usage: dict[str, Any] = {}
        started = time.monotonic()
        throttle_count = self.gate.throttle_count
        throttle_wait_ms = self.gate.throttle_wait_ms
        for attempt in range(1, MAX_PHASE_ATTEMPTS + 1):
            if on_attempt:
                on_attempt(attempt)
            phase_payload = dict(payload)
            if errors:
                phase_payload["validation_feedback"] = (
                    "The previous result failed. Correct every error while preserving valid work:\n- "
                    + "\n- ".join(errors)
                )
            body = {
                "model": self.model,
                "max_tokens": 8_000,
                "system": system,
                "messages": [{"role": "user", "content": json.dumps(phase_payload, default=str)}],
                "tools": [
                    {
                        "name": tool_name,
                        "description": description,
                        "input_schema": contract.model_json_schema(by_alias=True),
                    }
                ],
                "tool_choice": {"type": "tool", "name": tool_name},
            }
            try:
                active_client = (
                    repair_model_client
                    if attempt > 1 and repair_model_client is not None
                    else model_client or self.model_client
                )

                async def create_message(
                    request_body: dict[str, Any] = body,
                    client: MessagesModelClient = active_client,
                ) -> dict[str, Any]:
                    return await client.create_message(request_body)

                response = await self.gate.call(create_message)
                for key, value in _usage(response).items():
                    total_usage[key] = total_usage.get(key, 0) + value
                value = contract.model_validate(_tool_input(response, tool_name))
                validator(value)
                return ProgressivePhaseResult(
                    value=value,
                    attempt_count=attempt,
                    usage=total_usage,
                    latency_ms=(time.monotonic() - started) * 1000,
                    throttle_count=self.gate.throttle_count - throttle_count,
                    throttle_wait_ms=self.gate.throttle_wait_ms - throttle_wait_ms,
                )
            except asyncio.CancelledError:
                raise
            except (AnthropicMessagesError, httpx.RequestError, ValueError) as exc:
                safe = _safe_phase_error(exc)
                if safe not in errors:
                    errors.append(safe)
                if attempt == MAX_PHASE_ATTEMPTS:
                    exc.progressive_usage = total_usage
                    exc.progressive_latency_ms = (time.monotonic() - started) * 1000
                    exc.progressive_throttle_count = self.gate.throttle_count - throttle_count
                    exc.progressive_throttle_wait_ms = self.gate.throttle_wait_ms - throttle_wait_ms
                    raise
        raise AssertionError("Unreachable progressive authoring attempt loop")

    async def create_plan(
        self,
        *,
        prompt: str,
        semantic_projection: dict[str, Any],
        validator: Callable[[DashboardPlan], None],
        on_attempt: Callable[[int], None] | None = None,
    ) -> ProgressivePhaseResult:
        return await self._phase(
            tool_name="submit_dashboard_plan",
            description="Return one governed dashboard plan with stable chart and tile IDs.",
            system=(
                "Plan a governed business dashboard using only exact explores, dimensions, and approved metrics from "
                "semantic_context. Every chart is required unless the request explicitly says optional. Return stable "
                "chart_id and tile_id values, exact fields, one visualization, section, order, a non-overlapping "
                "36-column provisional layout, and shared-filter intent. Filters must copy complete field IDs and "
                "explicit per-tile mappings. Time-series charts require an applicable bounded date filter. Do not "
                "write chart query objects, SQL, renderer code, or placeholders."
            ),
            payload={"request": prompt, "semantic_context": semantic_projection},
            contract=DashboardPlan,
            validator=validator,
            on_attempt=on_attempt,
        )

    async def create_chart(
        self,
        *,
        intent: DashboardChartIntent,
        context: DashboardSemanticContext,
        filters: list[DashboardFilterRule],
        validator: Callable[[ChartDefinition], None],
        on_attempt: Callable[[int], None] | None = None,
    ) -> ProgressivePhaseResult:
        return await self._phase(
            tool_name="submit_chart_definition",
            description="Return exactly one governed chart definition for the supplied intent.",
            system=(
                "Create exactly one SignalPilot ChartDefinition. Copy chart ID, explore, dimensions, metrics, project "
                "and commit exactly from the intent and semantic context. Use only the requested visualization. KPI "
                "fields and Cartesian y fields come from metrics; Cartesian x fields come from dimensions. Add useful "
                "sorts, bounded limits, exact encodings, and meaningful lower-grain drill paths when available. Never "
                "emit SQL, layout, filters, another chart, or an invented field."
            ),
            payload={
                "intent": intent.model_dump(mode="json", exclude_none=True),
                "semantic_context": relevant_explore_projection(context, intent.explore_name),
                "shared_filters": [rule.model_dump(mode="json", by_alias=True, exclude_none=True) for rule in filters],
            },
            contract=ChartDefinition,
            validator=validator,
            on_attempt=on_attempt,
            model_client=self.chart_model_client,
            repair_model_client=self.model_client,
        )

    async def merge(
        self,
        *,
        plan: DashboardPlan,
        charts: list[ChartDefinition],
        validator: Callable[[DashboardMergeResult], None],
        on_attempt: Callable[[int], None] | None = None,
    ) -> ProgressivePhaseResult:
        current = {
            chart.id: {
                "title": chart.title,
                "visualization": (
                    chart.visualization.config.seriesType
                    if chart.visualization.type == "cartesian"
                    else "kpi"
                    if chart.visualization.type == "big_number"
                    else "table"
                ),
            }
            for chart in charts
        }
        return await self._phase(
            tool_name="submit_dashboard_merge",
            description="Arrange validated charts without changing their governed definitions.",
            system=(
                "Finalize dashboard name, description, chart titles, sections, ordering, and non-overlapping geometry "
                "on a 36-column grid. You may refine shared-filter tile mappings using only supplied filter and tile IDs. "
                "Return every supplied chart ID exactly once. You may not return or alter queries, encodings, drills, "
                "filter definitions, project bindings, or chart IDs."
            ),
            payload={
                "plan": plan.model_dump(mode="json", by_alias=True, exclude_none=True),
                "validated_charts": current,
            },
            contract=DashboardMergeResult,
            validator=validator,
            on_attempt=on_attempt,
        )


def _safe_phase_error(exc: BaseException) -> str:
    if isinstance(exc, AnthropicMessagesError):
        if exc.status_code == 429:
            return "The model provider is temporarily rate limited."
        if exc.status_code >= 500:
            return "The model provider is temporarily unavailable."
        return "The model provider rejected the authoring request."
    if isinstance(exc, httpx.RequestError):
        return "The model provider is temporarily unavailable."
    return str(exc)[:2000]


def validate_dashboard_plan(plan: DashboardPlan, context: DashboardSemanticContext) -> None:
    explores = {explore.name: explore for explore in context.explores}
    tile_ids = {intent.tile_id for intent in plan.intents}
    for intent in plan.intents:
        explore = explores.get(intent.explore_name)
        if explore is None:
            raise ValueError(f"Unknown explore: {intent.explore_name}")
        dimensions = {field.field_id for field in explore.dimensions}
        metrics = {metric.field_id for metric in explore.metrics}
        unknown_dimensions = set(intent.dimensions) - dimensions
        unknown_metrics = set(intent.metrics) - metrics
        if unknown_dimensions:
            raise ValueError(f"Unknown dimension: {sorted(unknown_dimensions)[0]}")
        if unknown_metrics:
            raise ValueError(f"Unknown metric: {sorted(unknown_metrics)[0]}")
        if intent.visualization in {"bar", "line", "area"} and not intent.dimensions:
            raise ValueError(f"Chart {intent.chart_id} requires a governed dimension")
        if intent.visualization in {"line", "area"}:
            applicable_window = False
            logical_types = {field.field_id: field.logical_type for field in explore.dimensions}
            for rule in plan.filters:
                if rule.id not in intent.shared_filter_ids:
                    continue
                explicit = (rule.tileTargets or {}).get(intent.tile_id)
                if explicit is False:
                    continue
                target = explicit or rule.target
                if (
                    target.tableName == intent.explore_name
                    and logical_types.get(target.fieldId) in {"date", "timestamp"}
                    and _bounded_filter(rule)
                ):
                    applicable_window = True
                    break
            if not applicable_window:
                raise ValueError(f"Time-series chart {intent.chart_id} requires an applicable bounded date filter")
    for rule in plan.filters:
        targets = [rule.target, *(target for target in (rule.tileTargets or {}).values() if target is not False)]
        for target in targets:
            explore = explores.get(target.tableName)
            valid = {field.field_id for field in explore.dimensions} if explore else set()
            if target.fieldId not in valid:
                raise ValueError(f"Unknown dashboard filter target: {target.tableName}.{target.fieldId}")
        unknown_tiles = set(rule.tileTargets or {}) - tile_ids
        if unknown_tiles:
            raise ValueError(f"Dashboard filter references an unknown tile: {sorted(unknown_tiles)[0]}")
    _validate_layout([intent.layout for intent in plan.intents])


def _bounded_filter(rule: DashboardFilterRule) -> bool:
    values = list(rule.values or [])
    if rule.operator == "inBetween":
        return len(values) == 2 and all(value not in {None, ""} for value in values)
    if rule.operator == "inThePast":
        return (
            len(values) == 1
            and isinstance(values[0], (int, float))
            and not isinstance(values[0], bool)
            and values[0] > 0
            and rule.settings is not None
            and rule.settings.unitOfTime is not None
        )
    return (
        rule.operator in {"inTheCurrent", "inPeriodToDate"}
        and rule.settings is not None
        and rule.settings.unitOfTime is not None
    )


def validate_chart_for_intent(
    chart: ChartDefinition,
    *,
    intent: DashboardChartIntent,
    plan: DashboardPlan,
    context: DashboardSemanticContext,
    timezone: str,
) -> None:
    if chart.id != intent.chart_id:
        raise ValueError(f"Chart ID must remain {intent.chart_id}")
    if not isinstance(chart.query, SemanticChartQuery):
        raise ValueError("Progressive chart agents may only create semantic charts")
    if chart.query.exploreName != intent.explore_name:
        raise ValueError(f"Chart explore must remain {intent.explore_name}")
    if chart.query.dimensions != intent.dimensions:
        raise ValueError("Chart dimensions must exactly match the validated plan")
    if chart.query.metrics != intent.metrics:
        raise ValueError("Chart metrics must exactly match the validated plan")
    if chart.query.projectId != context.project_id or chart.query.commitSha != context.commit_sha:
        raise ValueError("Chart project binding must exactly match the semantic preflight")
    actual_visualization = (
        chart.visualization.config.seriesType
        if chart.visualization.type == "cartesian"
        else "kpi"
        if chart.visualization.type == "big_number"
        else "table"
    )
    if actual_visualization != intent.visualization:
        raise ValueError(f"Chart visualization must remain {intent.visualization}")
    definition = assemble_dashboard_definition(
        plan=plan,
        charts=[chart],
        context=context,
        timezone=timezone,
    )
    validate_dashboard_semantics(definition, context)
    validate_time_series_default_windows(definition, context)


def _filters_for_intents(
    plan: DashboardPlan,
    intents: list[DashboardChartIntent],
) -> list[DashboardFilterRule]:
    selected_ids = {filter_id for intent in intents for filter_id in intent.shared_filter_ids}
    ready_tiles = {intent.tile_id for intent in intents}
    filters: list[DashboardFilterRule] = []
    for rule in plan.filters:
        if rule.id not in selected_ids:
            continue
        tile_targets = (
            {tile_id: target for tile_id, target in rule.tileTargets.items() if tile_id in ready_tiles}
            if rule.tileTargets
            else None
        )
        filters.append(rule.model_copy(update={"tileTargets": tile_targets}))
    return filters


def assemble_dashboard_definition(
    *,
    plan: DashboardPlan,
    charts: list[ChartDefinition],
    context: DashboardSemanticContext,
    timezone: str,
    merge: DashboardMergeResult | None = None,
    deterministic_fallback: bool = False,
) -> DashboardDefinition:
    if merge and merge.filter_mappings:
        mappings = {mapping.filter_id: mapping.tile_targets for mapping in merge.filter_mappings}
        plan = plan.model_copy(
            update={
                "filters": [
                    rule.model_copy(update={"tileTargets": mappings.get(rule.id, rule.tileTargets)})
                    for rule in plan.filters
                ]
            }
        )
    chart_by_id = {chart.id: chart for chart in charts}
    intents = [intent for intent in sorted(plan.intents, key=lambda item: item.order) if intent.chart_id in chart_by_id]
    merge_by_id = {tile.chart_id: tile for tile in merge.tiles} if merge else {}
    if merge:
        intents.sort(key=lambda intent: merge_by_id[intent.chart_id].order)
    fallback_layouts = deterministic_layout(intents) if deterministic_fallback else {}
    final_charts: list[ChartDefinition] = []
    tiles: list[DashboardTileDefinition] = []
    for intent in intents:
        chart = chart_by_id[intent.chart_id]
        merged = merge_by_id.get(intent.chart_id)
        if merged:
            chart = chart.model_copy(update={"title": merged.title})
            layout = merged.layout
        elif deterministic_fallback:
            layout = fallback_layouts[intent.chart_id]
        else:
            layout = intent.layout
        final_charts.append(chart)
        tiles.append(
            DashboardTileDefinition(
                uuid=intent.tile_id,
                tileSlug=intent.tile_id,
                type="saved_chart",
                x=layout.x,
                y=layout.y,
                w=layout.w,
                h=layout.h,
                chartId=intent.chart_id,
                properties=DashboardTileProperties(
                    title=chart.title,
                    chartName=chart.title,
                    chartSlug=intent.chart_id,
                    sectionTitle=merged.section if merged else intent.section,
                ),
            )
        )
    definition = DashboardDefinition(
        schemaVersion=1,
        name=merge.name if merge else plan.name,
        description=merge.description if merge else plan.description,
        filters=DashboardFilters(dimensions=_filters_for_intents(plan, intents), metrics=[]),
        tiles=tiles,
        charts=final_charts,
        signalPilot=DashboardSignalPilot(
            dashboardId="draft-progressive",
            projectId=context.project_id,
            connectionName=context.connection_name,
            commitSha=context.commit_sha,
            semanticFingerprint=context.semantic_fingerprint,
            timezone=timezone,
        ),
    )
    definition = canonicalize_dashboard_filter_targets(definition, context)
    return canonicalize_dashboard_time_series_defaults(definition, context)


def deterministic_layout(
    intents: list[DashboardChartIntent],
) -> dict[str, DashboardProvisionalLayout]:
    layouts: dict[str, DashboardProvisionalLayout] = {}
    x = 0
    y = 0
    row_height = 0
    for intent in intents:
        width = 12 if intent.visualization == "kpi" else 36
        height = 6 if intent.visualization == "kpi" else 10
        if x and x + width > 36:
            y += row_height
            x = 0
            row_height = 0
        if width == 36 and x:
            y += row_height
            x = 0
            row_height = 0
        layouts[intent.chart_id] = DashboardProvisionalLayout(x=x, y=y, w=width, h=height)
        x += width
        row_height = max(row_height, height)
        if x == 36:
            y += row_height
            x = 0
            row_height = 0
    return layouts


def validate_merge_result(merge: DashboardMergeResult, plan: DashboardPlan) -> None:
    expected = {intent.chart_id for intent in plan.intents}
    actual = {tile.chart_id for tile in merge.tiles}
    if actual != expected:
        raise ValueError("Merge must include every validated chart ID exactly once")
    filter_ids = {rule.id for rule in plan.filters}
    tile_ids = {intent.tile_id for intent in plan.intents}
    seen_filters: set[str] = set()
    for mapping in merge.filter_mappings:
        if mapping.filter_id not in filter_ids or mapping.filter_id in seen_filters:
            raise ValueError("Merge contains an unknown or duplicate shared filter mapping")
        seen_filters.add(mapping.filter_id)
        if set(mapping.tile_targets) - tile_ids:
            raise ValueError("Merge shared-filter mapping contains an unknown tile ID")
    _validate_layout([tile.layout for tile in merge.tiles])


def _validate_layout(layouts: list[DashboardProvisionalLayout]) -> None:
    for index, layout in enumerate(layouts):
        if layout.x + layout.w > 36:
            raise ValueError("Dashboard tile exceeds the 36-column grid")
        for other in layouts[index + 1 :]:
            horizontal = layout.x < other.x + other.w and other.x < layout.x + layout.w
            vertical = layout.y < other.y + other.h and other.y < layout.y + layout.h
            if horizontal and vertical:
                raise ValueError("Dashboard layout contains overlapping tiles")


def phase_provenance(
    *,
    phase: str,
    result: ProgressivePhaseResult | None,
    chart_id: str | None = None,
    fallback: bool = False,
) -> dict[str, Any]:
    return {
        "id": f"{phase}:{chart_id or 'dashboard'}:{time.time_ns()}",
        "phase": phase,
        **({"chart_id": chart_id} if chart_id else {}),
        "attempt_count": result.attempt_count if result else 0,
        "repair_count": max((result.attempt_count if result else 0) - 1, 0),
        "usage": result.usage if result else {},
        "latency_ms": result.latency_ms if result else 0,
        "throttle_count": result.throttle_count if result else 0,
        "throttle_wait_ms": result.throttle_wait_ms if result else 0,
        "fallback": fallback,
        "created_at": datetime.now(UTC).isoformat(),
    }


def safe_chart_failure(exc: BaseException) -> str:
    if isinstance(exc, AnthropicMessagesError):
        if exc.status_code == 429:
            return "This chart could not be generated because the model provider is rate limited."
        if exc.status_code >= 500:
            return "This chart could not be generated because the model provider is unavailable."
        return "This chart could not be generated because the model provider rejected it."
    return "This chart could not be validated against the governed semantic model."


def aggregate_usage(results: list[ProgressivePhaseResult]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for result in results:
        for key, value in result.usage.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                totals[key] = totals.get(key, 0) + value
    return totals
