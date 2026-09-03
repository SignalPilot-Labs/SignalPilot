"""Pure validators and deterministic assembly for dashboard authoring."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

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
