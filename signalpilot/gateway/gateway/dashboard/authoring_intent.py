"""Small model-authored dashboard intent and deterministic definition compiler."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Literal

from pydantic import Field

from gateway.dashboard.domain import (
    AndFilterGroup,
    CartesianChartConfig,
    CartesianConfig,
    CartesianLayout,
    ChartDefinition,
    ChartSignalPilot,
    ContractModel,
    DashboardDefinition,
    DashboardFieldTarget,
    DashboardFilterRule,
    DashboardFilters,
    DashboardSignalPilot,
    DashboardTileDefinition,
    DashboardTileProperties,
    FilterRule,
    FilterSettings,
    KpiChartConfig,
    KpiConfig,
    QueryFilters,
    SemanticChartQuery,
    SortField,
    TableChartConfig,
    TableConfig,
)
from gateway.models.dashboards import DashboardSemanticContext, DashboardSemanticExplore

VisualizationIntent = Literal["kpi", "table", "bar", "line", "area"]


class DashboardChartIntent(ContractModel):
    """Business and semantic choices the model is allowed to make for one chart."""

    ref: str = Field(min_length=1, max_length=80)
    visualization: VisualizationIntent
    exploreName: str = Field(min_length=1)
    dimensions: list[str] = Field(default_factory=list, max_length=4)
    metrics: list[str] = Field(default_factory=list, max_length=4)
    title: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    drillDimensions: list[str] = Field(default_factory=list, max_length=4)


class DashboardFilterIntent(ContractModel):
    """A governed dimension the model considers useful as a dashboard control."""

    exploreName: str = Field(min_length=1)
    fieldId: str = Field(min_length=1)
    label: str | None = Field(default=None, min_length=1, max_length=100)


class DashboardCreationIntent(ContractModel):
    """Creation-only model contract; renderer and persistence mechanics are excluded."""

    summary: str = Field(min_length=1, max_length=1000)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    charts: list[DashboardChartIntent] = Field(min_length=1, max_length=12)
    filters: list[DashboardFilterIntent] = Field(default_factory=list, max_length=4)


class DashboardIntentIssue(ContractModel):
    code: str = Field(min_length=1)
    path: str = Field(min_length=1)
    message: str = Field(min_length=1)
    rejectedValue: str | None = None
    allowedValues: list[str] = Field(default_factory=list)


class DashboardIntentValidationError(ValueError):
    """Structured semantic feedback suitable for a bounded model repair turn."""

    def __init__(self, issues: list[DashboardIntentIssue]) -> None:
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))

    def as_payload(self) -> list[dict[str, Any]]:
        return [issue.model_dump(mode="json", by_alias=True, exclude_none=True) for issue in self.issues]


class DashboardIntentRepairError(ValueError):
    """Safe terminal failure after bounded automatic semantic repair."""

    def __init__(self) -> None:
        super().__init__(
            "Dashboard authoring could not map the request to the project's governed fields after automatic repair. "
            "Try naming an available metric or dimension more explicitly."
        )


def _slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return (slug or fallback)[:64]


def _question(value: str) -> str:
    normalized = value.rstrip()
    return normalized if normalized.endswith("?") else f"{normalized}?"


def _governed_format(value: str | None) -> str | None:
    if value is None:
        return None
    aliases = {"number": "decimal", "percent": "percentage"}
    normalized = aliases.get(value, value)
    if normalized in {"integer", "decimal", "compact", "percentage"}:
        return normalized
    if normalized.startswith("currency:") and len(normalized) == 12 and normalized[9:].isupper():
        return normalized
    return None


def _intent_issues(
    intent: DashboardCreationIntent,
    context: DashboardSemanticContext,
) -> list[DashboardIntentIssue]:
    issues: list[DashboardIntentIssue] = []
    explores = {explore.name: explore for explore in context.explores}
    explore_names = list(explores)
    duplicate_refs = [ref for ref, count in Counter(chart.ref for chart in intent.charts).items() if count > 1]
    for ref in duplicate_refs:
        issues.append(
            DashboardIntentIssue(
                code="duplicate_chart_ref",
                path="charts",
                message=f"Chart ref must be unique: {ref}",
                rejectedValue=ref,
            )
        )
    for index, chart in enumerate(intent.charts):
        path = f"charts[{index}]"
        explore = explores.get(chart.exploreName)
        if explore is None:
            issues.append(
                DashboardIntentIssue(
                    code="unknown_explore",
                    path=f"{path}.exploreName",
                    message=f"Unknown explore: {chart.exploreName}",
                    rejectedValue=chart.exploreName,
                    allowedValues=explore_names,
                )
            )
            continue
        dimensions = {field.field_id: field for field in explore.dimensions}
        metrics = {metric.field_id: metric for metric in explore.metrics}
        for field_index, field_id in enumerate(chart.dimensions):
            if field_id not in dimensions:
                issues.append(
                    DashboardIntentIssue(
                        code="unknown_dimension",
                        path=f"{path}.dimensions[{field_index}]",
                        message=f"Unknown dimension for {chart.exploreName}: {field_id}",
                        rejectedValue=field_id,
                        allowedValues=list(dimensions),
                    )
                )
        for field_index, field_id in enumerate(chart.metrics):
            if field_id not in metrics:
                issues.append(
                    DashboardIntentIssue(
                        code="unknown_metric",
                        path=f"{path}.metrics[{field_index}]",
                        message=f"Unknown metric for {chart.exploreName}: {field_id}",
                        rejectedValue=field_id,
                        allowedValues=list(metrics),
                    )
                )
        for field_index, field_id in enumerate(chart.drillDimensions):
            if field_id not in dimensions:
                issues.append(
                    DashboardIntentIssue(
                        code="unknown_drill_dimension",
                        path=f"{path}.drillDimensions[{field_index}]",
                        message=f"Unknown drill dimension for {chart.exploreName}: {field_id}",
                        rejectedValue=field_id,
                        allowedValues=list(dimensions),
                    )
                )
        if not chart.metrics:
            issues.append(
                DashboardIntentIssue(
                    code="missing_metric",
                    path=f"{path}.metrics",
                    message=f"{chart.visualization} chart requires at least one governed metric",
                    allowedValues=list(metrics),
                )
            )
        if chart.visualization == "kpi" and (len(chart.metrics) != 1 or chart.dimensions):
            issues.append(
                DashboardIntentIssue(
                    code="incompatible_visualization",
                    path=path,
                    message="KPI charts require exactly one metric and no dimensions",
                )
            )
        if chart.visualization in {"bar", "line", "area"} and len(chart.dimensions) != 1:
            issues.append(
                DashboardIntentIssue(
                    code="missing_dimension",
                    path=f"{path}.dimensions",
                    message=f"{chart.visualization} chart requires exactly one governed dimension",
                    allowedValues=list(dimensions),
                )
            )
        if chart.visualization in {"line", "area"} and len(chart.dimensions) == 1:
            dimension = dimensions.get(chart.dimensions[0])
            if dimension is not None and dimension.logical_type not in {"date", "timestamp"}:
                date_dimensions = [
                    field.field_id for field in explore.dimensions if field.logical_type in {"date", "timestamp"}
                ]
                issues.append(
                    DashboardIntentIssue(
                        code="incompatible_visualization",
                        path=f"{path}.dimensions[0]",
                        message=f"{chart.visualization} chart requires a governed date or timestamp dimension",
                        rejectedValue=chart.dimensions[0],
                        allowedValues=date_dimensions,
                    )
                )
        repeated = set(chart.dimensions) & set(chart.drillDimensions)
        if repeated or len(chart.drillDimensions) != len(set(chart.drillDimensions)):
            issues.append(
                DashboardIntentIssue(
                    code="invalid_drill_hierarchy",
                    path=f"{path}.drillDimensions",
                    message="Drill dimensions must be distinct and cannot repeat a query dimension",
                )
            )
    for index, filter_intent in enumerate(intent.filters):
        path = f"filters[{index}]"
        explore = explores.get(filter_intent.exploreName)
        if explore is None:
            issues.append(
                DashboardIntentIssue(
                    code="unknown_explore",
                    path=f"{path}.exploreName",
                    message=f"Unknown filter explore: {filter_intent.exploreName}",
                    rejectedValue=filter_intent.exploreName,
                    allowedValues=explore_names,
                )
            )
            continue
        dimensions = [field.field_id for field in explore.dimensions]
        if filter_intent.fieldId not in dimensions:
            issues.append(
                DashboardIntentIssue(
                    code="unsupported_filter",
                    path=f"{path}.fieldId",
                    message=f"Filter must reference a governed dimension: {filter_intent.fieldId}",
                    rejectedValue=filter_intent.fieldId,
                    allowedValues=dimensions,
                )
            )
    return issues


def _tile_layout(intent: DashboardCreationIntent) -> dict[int, tuple[int, int, int, int]]:
    layout: dict[int, tuple[int, int, int, int]] = {}
    kpi_indexes = [index for index, chart in enumerate(intent.charts) if chart.visualization == "kpi"]
    y = 0
    for start in range(0, len(kpi_indexes), 3):
        row = kpi_indexes[start : start + 3]
        width = 36 // len(row)
        for position, chart_index in enumerate(row):
            layout[chart_index] = (position * width, y, width, 5)
        y += 5
    for index, chart in enumerate(intent.charts):
        if chart.visualization != "kpi":
            layout[index] = (0, y, 36, 10)
            y += 10
    return layout


def _date_field(explore: DashboardSemanticExplore, preferred: list[str]) -> str | None:
    available = {
        field.field_id for field in explore.dimensions if field.logical_type in {"date", "timestamp"}
    }
    return next((field_id for field_id in preferred if field_id in available), None) or next(
        (field.field_id for field in explore.dimensions if field.field_id in available),
        None,
    )


def _compiled_filters(
    *,
    intent: DashboardCreationIntent,
    context: DashboardSemanticContext,
    charts: list[ChartDefinition],
    tiles: list[DashboardTileDefinition],
    include_filters: bool,
) -> list[DashboardFilterRule]:
    if not include_filters:
        return []
    explores = {explore.name: explore for explore in context.explores}
    chart_counts = Counter(chart.query.exploreName for chart in charts)
    selected: list[DashboardFilterIntent] = []
    seen: set[tuple[str, str]] = set()

    def select(candidate: DashboardFilterIntent) -> None:
        key = (candidate.exploreName, candidate.fieldId)
        if key not in seen:
            seen.add(key)
            selected.append(candidate)

    requested_dates = [
        candidate
        for candidate in intent.filters
        if next(
            (
                field.logical_type
                for field in explores[candidate.exploreName].dimensions
                if field.field_id == candidate.fieldId
            ),
            None,
        )
        in {"date", "timestamp"}
    ]
    time_series_explores = {
        chart.query.exploreName
        for chart in charts
        if chart.visualization.type == "cartesian" and chart.visualization.config.seriesType in {"line", "area"}
    }
    for explore_name in sorted(time_series_explores, key=lambda value: -chart_counts[value]):
        explore = explores[explore_name]
        preferred = [
            candidate.fieldId for candidate in requested_dates if candidate.exploreName == explore_name
        ] + [
            chart.query.dimensions[0]
            for chart in charts
            if chart.query.exploreName == explore_name
            and chart.visualization.type == "cartesian"
            and chart.visualization.config.seriesType in {"line", "area"}
        ]
        field_id = _date_field(explore, preferred)
        if field_id:
            select(DashboardFilterIntent(exploreName=explore_name, fieldId=field_id))
    if not selected:
        for candidate in requested_dates:
            select(candidate)
            break
    if not selected:
        for explore_name, _count in chart_counts.most_common():
            field_id = _date_field(explores[explore_name], [])
            if field_id:
                select(DashboardFilterIntent(exploreName=explore_name, fieldId=field_id))
                break
    for candidate in intent.filters:
        explore = explores[candidate.exploreName]
        logical_type = next(field.logical_type for field in explore.dimensions if field.field_id == candidate.fieldId)
        if logical_type not in {"date", "timestamp"}:
            select(candidate)
        if len(selected) >= 3:
            break
    if not selected:
        raise DashboardIntentValidationError(
            [
                DashboardIntentIssue(
                    code="governed_filter_unavailable",
                    path="filters",
                    message="Dashboard creation requires a governed filter dimension, but none is available",
                )
            ]
        )

    rules: list[DashboardFilterRule] = []
    tile_by_chart = {tile.chartId: tile for tile in tiles}
    for index, candidate in enumerate(selected):
        explore = explores[candidate.exploreName]
        field = next(field for field in explore.dimensions if field.field_id == candidate.fieldId)
        target = DashboardFieldTarget(tableName=explore.name, fieldId=field.field_id)
        tile_targets: dict[str, DashboardFieldTarget | Literal[False]] = {}
        for chart in charts:
            tile = tile_by_chart[chart.id]
            tile_targets[tile.uuid] = target if chart.query.exploreName == explore.name else False
        is_date = field.logical_type in {"date", "timestamp"}
        rules.append(
            DashboardFilterRule(
                id=f"filter-{index + 1}-{_slug(field.field_id, fallback='field')}",
                operator="inThePast" if is_date else "equals",
                values=[30] if is_date else [],
                target=target,
                tileTargets=tile_targets,
                label=candidate.label or field.label or field.column.replace("_", " ").title(),
                settings=FilterSettings(unitOfTime="days") if is_date else None,
            )
        )
    return rules


def compile_dashboard_creation_intent(
    intent: DashboardCreationIntent,
    context: DashboardSemanticContext,
    *,
    timezone: str,
    include_filters: bool = True,
) -> DashboardDefinition:
    """Compile model-authored semantic choices into a complete governed definition."""

    issues = _intent_issues(intent, context)
    if issues:
        raise DashboardIntentValidationError(issues)
    explores = {explore.name: explore for explore in context.explores}
    layout = _tile_layout(intent)
    charts: list[ChartDefinition] = []
    tiles: list[DashboardTileDefinition] = []
    for index, chart_intent in enumerate(intent.charts):
        explore = explores[chart_intent.exploreName]
        metrics = {metric.field_id: metric for metric in explore.metrics}
        chart_slug = f"{index + 1}-{_slug(chart_intent.ref or chart_intent.title, fallback='chart')}"
        chart_id = f"chart-{chart_slug}"
        tile_id = f"tile-{chart_slug}"
        if chart_intent.visualization == "kpi":
            visualization = KpiChartConfig(
                type="big_number",
                config=KpiConfig(
                    field=chart_intent.metrics[0],
                    format=_governed_format(metrics[chart_intent.metrics[0]].format),
                ),
            )
            limit = 1
            sorts: list[SortField] = []
        elif chart_intent.visualization == "table":
            visualization = TableChartConfig(
                type="table",
                config=TableConfig(
                    columns=[*chart_intent.dimensions, *chart_intent.metrics],
                    groups=chart_intent.dimensions or None,
                ),
            )
            limit = 100
            sorts = [SortField(fieldId=chart_intent.metrics[0], descending=True)]
        else:
            visualization = CartesianChartConfig(
                type="cartesian",
                config=CartesianConfig(
                    seriesType=chart_intent.visualization,
                    layout=CartesianLayout(
                        xField=chart_intent.dimensions[0],
                        yField=chart_intent.metrics,
                    ),
                ),
            )
            limit = 100
            sorts = [
                SortField(
                    fieldId=(
                        chart_intent.dimensions[0]
                        if chart_intent.visualization in {"line", "area"}
                        else chart_intent.metrics[0]
                    ),
                    descending=chart_intent.visualization == "bar",
                )
            ]
        query_filters = QueryFilters()
        if not include_filters and chart_intent.visualization in {"line", "area"}:
            field_id = chart_intent.dimensions[0]
            query_filters = QueryFilters(
                dimensions=AndFilterGroup(
                    id=f"window-{chart_slug}",
                    **{
                        "and": [
                            FilterRule(
                                id=f"window-rule-{chart_slug}",
                                operator="inThePast",
                                values=[30],
                                target={"fieldId": field_id},
                                settings=FilterSettings(unitOfTime="days"),
                            )
                        ]
                    },
                )
            )
        query = SemanticChartQuery(
            kind="semantic",
            exploreName=explore.name,
            dimensions=chart_intent.dimensions,
            metrics=chart_intent.metrics,
            filters=query_filters,
            sorts=sorts,
            limit=limit,
            timezone=timezone,
            projectId=context.project_id,
            commitSha=context.commit_sha,
        )
        charts.append(
            ChartDefinition(
                id=chart_id,
                title=chart_intent.title,
                question=_question(chart_intent.question),
                description=chart_intent.description,
                query=query,
                visualization=visualization,
                signalPilot=ChartSignalPilot(
                    crossFilter=chart_intent.visualization != "kpi",
                    drillDimensions=chart_intent.drillDimensions or None,
                    tableGroups=chart_intent.dimensions or None if chart_intent.visualization == "table" else None,
                    provenanceRef=f"agent-intent:{chart_slug}",
                ),
            )
        )
        x, y, width, height = layout[index]
        tiles.append(
            DashboardTileDefinition(
                uuid=tile_id,
                tileSlug=chart_slug,
                type="saved_chart",
                x=x,
                y=y,
                w=width,
                h=height,
                properties=DashboardTileProperties(title=chart_intent.title, chartSlug=chart_slug),
                chartId=chart_id,
            )
        )
    filters = _compiled_filters(
        intent=intent,
        context=context,
        charts=charts,
        tiles=tiles,
        include_filters=include_filters,
    )
    return DashboardDefinition(
        schemaVersion=1,
        name=intent.name,
        description=intent.description,
        filters=DashboardFilters(dimensions=filters, metrics=[]),
        tiles=tiles,
        charts=charts,
        signalPilot=DashboardSignalPilot(
            dashboardId="draft-intent",
            projectId=context.project_id,
            connectionName=context.connection_name,
            commitSha=context.commit_sha,
            semanticFingerprint=context.semantic_fingerprint,
            timezone=timezone,
        ),
    )
