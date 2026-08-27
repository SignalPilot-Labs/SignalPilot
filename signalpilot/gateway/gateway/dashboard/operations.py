"""Typed dashboard authoring operations and semantic validation."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from gateway.dashboard.compiler import compile_metric_query
from gateway.dashboard.domain import (
    ChartDefinition,
    ContractModel,
    DashboardDefinition,
    DashboardFieldTarget,
    DashboardFilterRule,
    DashboardTileDefinition,
    SemanticChartQuery,
)
from gateway.models.dashboards import DashboardSemanticContext


class RenameDashboard(ContractModel):
    operation: Literal["rename_dashboard"]
    name: str = Field(min_length=1, max_length=200)


class AddChart(ContractModel):
    operation: Literal["add_chart"]
    chart: ChartDefinition
    tile: DashboardTileDefinition


class RemoveChart(ContractModel):
    operation: Literal["remove_chart"]
    chart_id: str = Field(min_length=1)


class ReplaceMetric(ContractModel):
    operation: Literal["replace_metric"]
    chart_id: str = Field(min_length=1)
    old_metric: str = Field(min_length=1)
    new_metric: str = Field(min_length=1)


class DimensionOperation(ContractModel):
    operation: Literal["add_dimension", "remove_dimension"]
    chart_id: str = Field(min_length=1)
    dimension: str = Field(min_length=1)


class AddFilterControl(ContractModel):
    operation: Literal["add_filter_control"]
    filter: DashboardFilterRule


class ChangeVisualization(ContractModel):
    operation: Literal["change_visualization"]
    chart_id: str = Field(min_length=1)
    visualization: Literal["kpi", "table", "bar", "line", "area"]


class MoveChart(ContractModel):
    operation: Literal["move_chart"]
    tile_uuid: str = Field(min_length=1)
    x: int = Field(ge=0, le=35)
    y: int = Field(ge=0)


class ResizeChart(ContractModel):
    operation: Literal["resize_chart"]
    tile_uuid: str = Field(min_length=1)
    w: int = Field(ge=1, le=36)
    h: int = Field(ge=1)


class DescribeChart(ContractModel):
    operation: Literal["describe_chart"]
    chart_id: str = Field(min_length=1)
    description: str = Field(min_length=1, max_length=1000)


DashboardOperation = Annotated[
    RenameDashboard
    | AddChart
    | RemoveChart
    | ReplaceMetric
    | DimensionOperation
    | AddFilterControl
    | ChangeVisualization
    | MoveChart
    | ResizeChart
    | DescribeChart,
    Field(discriminator="operation"),
]
dashboard_operation_adapter = TypeAdapter(list[DashboardOperation])


def _chart_index(definition: DashboardDefinition, chart_id: str) -> int:
    index = next((index for index, chart in enumerate(definition.charts) if chart.id == chart_id), None)
    if index is None:
        raise ValueError(f"Unknown chart: {chart_id}")
    return index


def _tile_index(definition: DashboardDefinition, tile_uuid: str) -> int:
    index = next((index for index, tile in enumerate(definition.tiles) if tile.uuid == tile_uuid), None)
    if index is None:
        raise ValueError(f"Unknown tile: {tile_uuid}")
    return index


def apply_dashboard_operations(
    definition: DashboardDefinition,
    operations: list[DashboardOperation] | list[dict],
) -> DashboardDefinition:
    """Apply stable-ID mutations while leaving unrelated charts untouched."""
    parsed = dashboard_operation_adapter.validate_python(operations)
    current = definition
    for operation in parsed:
        if isinstance(operation, RenameDashboard):
            current = current.model_copy(update={"name": operation.name})
            continue
        if isinstance(operation, AddChart):
            if operation.chart.id in {chart.id for chart in current.charts}:
                raise ValueError(f"Chart already exists: {operation.chart.id}")
            if operation.tile.uuid in {tile.uuid for tile in current.tiles}:
                raise ValueError(f"Tile already exists: {operation.tile.uuid}")
            if operation.tile.chartId != operation.chart.id:
                raise ValueError("Added tile must reference the added chart")
            current = current.model_copy(
                update={"charts": [*current.charts, operation.chart], "tiles": [*current.tiles, operation.tile]}
            )
            continue
        if isinstance(operation, RemoveChart):
            _chart_index(current, operation.chart_id)
            charts = [chart for chart in current.charts if chart.id != operation.chart_id]
            tiles = [tile for tile in current.tiles if tile.chartId != operation.chart_id]
            if not charts:
                raise ValueError("A dashboard must retain at least one chart")
            current = current.model_copy(update={"charts": charts, "tiles": tiles})
            continue
        if isinstance(operation, AddFilterControl):
            filters = current.filters
            if operation.filter.id in {item.id for item in filters.dimensions}:
                raise ValueError(f"Filter already exists: {operation.filter.id}")
            current = current.model_copy(
                update={"filters": filters.model_copy(update={"dimensions": [*filters.dimensions, operation.filter]})}
            )
            continue
        if isinstance(operation, (MoveChart, ResizeChart)):
            index = _tile_index(current, operation.tile_uuid)
            tile = current.tiles[index]
            update = (
                {"x": operation.x, "y": operation.y}
                if isinstance(operation, MoveChart)
                else {"w": operation.w, "h": operation.h}
            )
            tiles = list(current.tiles)
            tiles[index] = tile.model_copy(update=update)
            current = current.model_copy(update={"tiles": tiles})
            continue

        index = _chart_index(current, operation.chart_id)
        chart = current.charts[index]
        if isinstance(operation, DescribeChart):
            updated_chart = chart.model_copy(update={"description": operation.description})
        else:
            if not isinstance(chart.query, SemanticChartQuery):
                raise ValueError(f"{operation.operation} requires a semantic chart")
            query = chart.query
            visualization = chart.visualization.model_dump(mode="json", by_alias=True, exclude_none=True)
            if isinstance(operation, ReplaceMetric):
                if operation.old_metric not in query.metrics:
                    raise ValueError(f"Metric is not used by chart: {operation.old_metric}")
                metrics = [operation.new_metric if item == operation.old_metric else item for item in query.metrics]
                query = query.model_copy(update={"metrics": metrics})
                if visualization["type"] == "big_number":
                    if visualization["config"]["field"] == operation.old_metric:
                        visualization["config"]["field"] = operation.new_metric
                elif visualization["type"] == "table":
                    visualization["config"]["columns"] = [
                        operation.new_metric if item == operation.old_metric else item
                        for item in visualization["config"]["columns"]
                    ]
                else:
                    visualization["config"]["layout"]["yField"] = [
                        operation.new_metric if item == operation.old_metric else item
                        for item in visualization["config"]["layout"]["yField"]
                    ]
            elif isinstance(operation, DimensionOperation):
                dimensions = list(query.dimensions)
                if operation.operation == "add_dimension" and operation.dimension not in dimensions:
                    dimensions.append(operation.dimension)
                elif operation.operation == "remove_dimension":
                    if operation.dimension not in dimensions:
                        raise ValueError(f"Dimension is not used by chart: {operation.dimension}")
                    dimensions.remove(operation.dimension)
                query = query.model_copy(update={"dimensions": dimensions})
                if visualization["type"] == "table":
                    columns = list(visualization["config"]["columns"])
                    if operation.operation == "add_dimension" and operation.dimension not in columns:
                        columns.insert(0, operation.dimension)
                    elif operation.operation == "remove_dimension":
                        columns = [item for item in columns if item != operation.dimension]
                    visualization["config"]["columns"] = columns
                elif (
                    visualization["type"] == "cartesian"
                    and operation.operation == "remove_dimension"
                    and visualization["config"]["layout"]["xField"] == operation.dimension
                ):
                    if not dimensions:
                        raise ValueError("Cannot remove the encoded Cartesian dimension")
                    visualization["config"]["layout"]["xField"] = dimensions[0]
            elif isinstance(operation, ChangeVisualization):
                outputs = [*query.dimensions, *query.metrics]
                if operation.visualization == "kpi":
                    visualization = {"type": "big_number", "config": {"field": query.metrics[0]}}
                elif operation.visualization == "table":
                    visualization = {"type": "table", "config": {"columns": outputs}}
                else:
                    if not query.dimensions:
                        raise ValueError("Cartesian charts require a dimension")
                    visualization = {
                        "type": "cartesian",
                        "config": {
                            "seriesType": operation.visualization,
                            "layout": {"xField": query.dimensions[0], "yField": query.metrics},
                        },
                    }
                updated_chart = chart.model_copy(update={"query": query, "visualization": visualization})
                charts = list(current.charts)
                charts[index] = ChartDefinition.model_validate(
                    updated_chart.model_dump(mode="json", by_alias=True, exclude_none=True)
                )
                current = current.model_copy(update={"charts": charts})
                continue
            chart_payload = chart.model_dump(mode="json", by_alias=True, exclude_none=True)
            chart_payload["query"] = query.model_dump(mode="json", by_alias=True, exclude_none=True)
            chart_payload["visualization"] = visualization
            updated_chart = ChartDefinition.model_validate(chart_payload)
        charts = list(current.charts)
        charts[index] = updated_chart
        current = current.model_copy(update={"charts": charts})

    return DashboardDefinition.model_validate(current.model_dump(mode="json", by_alias=True, exclude_none=True))


def validate_dashboard_semantics(definition: DashboardDefinition, context: DashboardSemanticContext) -> None:
    """Reject hallucinated explores, dimensions, and metrics before preview or save."""
    fields_by_explore = {
        explore.name: {
            *(field.field_id for field in explore.dimensions),
            *(metric.field_id for metric in explore.metrics),
        }
        for explore in context.explores
    }
    for chart in definition.charts:
        if isinstance(chart.query, SemanticChartQuery):
            compile_metric_query(chart.query, context)
            valid_fields = fields_by_explore.get(chart.query.exploreName, set())
            drill_dimensions = chart.signalPilot.drillDimensions or []
            repeated_query_dimensions = [
                field_id for field_id in drill_dimensions if field_id in chart.query.dimensions
            ]
            if repeated_query_dimensions:
                raise ValueError(
                    f"Drill hierarchy for chart {chart.id} repeats query dimension: {repeated_query_dimensions[0]}"
                )
            if len(drill_dimensions) != len(set(drill_dimensions)):
                raise ValueError(f"Drill hierarchy for chart {chart.id} repeats a drill level")
            for field_id in drill_dimensions:
                if field_id not in valid_fields:
                    raise ValueError(f"Unknown drill field: {field_id}")
            for field_id in chart.signalPilot.tableGroups or []:
                if field_id not in valid_fields:
                    raise ValueError(f"Unknown table group field: {field_id}")
    for rule in definition.filters.dimensions:
        targets = [rule.target, *(target for target in (rule.tileTargets or {}).values() if target is not False)]
        for target in targets:
            if target.tableName not in fields_by_explore or target.fieldId not in fields_by_explore[target.tableName]:
                raise ValueError(f"Unknown dashboard filter target: {target.tableName}.{target.fieldId}")


class DashboardTimeSeriesWindowError(ValueError):
    """A line or area chart cannot prove a complete bounded initial view."""

    code = "dashboard_time_series_window_required"
    recovery = "Narrow the default date window or use coarser time aggregation."


def _has_bounded_default(rule: DashboardFilterRule) -> bool:
    values = list(rule.values or [])
    if rule.operator == "inBetween":
        if len(values) != 2 or any(value is None or value == "" for value in values):
            return False
        try:
            return values[0] < values[1]  # type: ignore[operator]
        except TypeError:
            return False
    if rule.operator == "inThePast":
        return (
            len(values) == 1
            and not isinstance(values[0], bool)
            and isinstance(values[0], (int, float))
            and math.isfinite(values[0])
            and values[0] > 0
            and rule.settings is not None
            and rule.settings.unitOfTime is not None
        )
    return (
        rule.operator in {"inTheCurrent", "inPeriodToDate"}
        and rule.settings is not None
        and rule.settings.unitOfTime is not None
    )


def validate_time_series_default_windows(
    definition: DashboardDefinition,
    context: DashboardSemanticContext,
) -> None:
    """Require every line/area tile to open on a bounded date or timestamp window."""

    explores = {
        explore.name: {field.field_id: field.logical_type for field in explore.dimensions}
        for explore in context.explores
    }
    tiles_by_chart = {
        chart.id: [tile for tile in definition.tiles if tile.chartId == chart.id]
        for chart in definition.charts
    }
    for chart in definition.charts:
        if (
            chart.visualization.type != "cartesian"
            or chart.visualization.config.seriesType not in {"line", "area"}
        ):
            continue
        valid_window = False
        for tile in tiles_by_chart[chart.id]:
            for rule in definition.filters.dimensions:
                explicit_target = (rule.tileTargets or {}).get(tile.uuid)
                if explicit_target is False:
                    continue
                if explicit_target is None:
                    if not isinstance(chart.query, SemanticChartQuery):
                        continue
                    if rule.target.tableName != chart.query.exploreName:
                        continue
                    target = rule.target
                else:
                    target = explicit_target
                if isinstance(chart.query, SemanticChartQuery):
                    logical_type = explores.get(chart.query.exploreName, {}).get(target.fieldId)
                else:
                    logical_type = next(
                        (
                            binding.logicalType
                            for binding in chart.query.outputBindings
                            if binding.dashboardFieldId == target.fieldId
                        ),
                        None,
                    )
                if logical_type in {"date", "timestamp"} and _has_bounded_default(rule):
                    valid_window = True
                    break
            if valid_window:
                break
        if not valid_window:
            raise DashboardTimeSeriesWindowError(
                f"{chart.title} requires an applicable date or timestamp filter with a valid bounded default. "
                f"{DashboardTimeSeriesWindowError.recovery}"
            )


def canonicalize_dashboard_filter_targets(
    definition: DashboardDefinition,
    context: DashboardSemanticContext,
) -> DashboardDefinition:
    """Resolve an unqualified governed column to its exact semantic field ID.

    Model-authored filters occasionally preserve the explore name but shorten a
    field such as ``orders.order_date`` to ``order_date``. Only that exact,
    unambiguous column alias is recoverable; unknown explores and fields remain
    unchanged so semantic validation still rejects them.
    """
    aliases_by_explore: dict[str, dict[str, str | None]] = {}
    for explore in context.explores:
        aliases: dict[str, str | None] = {}
        for field in explore.dimensions:
            if field.column in aliases and aliases[field.column] != field.field_id:
                aliases[field.column] = None
            else:
                aliases[field.column] = field.field_id
        aliases_by_explore[explore.name] = aliases

    def canonicalize(target: DashboardFieldTarget) -> DashboardFieldTarget:
        if target.isSqlColumn:
            return target
        canonical_field_id = aliases_by_explore.get(target.tableName, {}).get(target.fieldId)
        if canonical_field_id is None or canonical_field_id == target.fieldId:
            return target
        return target.model_copy(update={"fieldId": canonical_field_id})

    changed = False
    dimensions: list[DashboardFilterRule] = []
    for rule in definition.filters.dimensions:
        target = canonicalize(rule.target)
        tile_targets = None
        if rule.tileTargets is not None:
            tile_targets = {
                tile_uuid: value if value is False else canonicalize(value)
                for tile_uuid, value in rule.tileTargets.items()
            }
        if target != rule.target or tile_targets != rule.tileTargets:
            changed = True
            rule = rule.model_copy(update={"target": target, "tileTargets": tile_targets})
        dimensions.append(rule)

    if not changed:
        return definition
    return definition.model_copy(update={"filters": definition.filters.model_copy(update={"dimensions": dimensions})})


def has_custom_sql(definition: DashboardDefinition) -> bool:
    return any(chart.query.kind == "sql" for chart in definition.charts)
