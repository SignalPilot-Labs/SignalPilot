"""Strict DashboardDefinition v1 mirrored from the TypeScript contract.

The supported shapes are a deliberate subset of the MIT-licensed Lightdash
contracts pinned at b91bd2273f38fdc58702c71f538b6b5d5ae462c5. See the web
dashboard CONTRACT_MAPPING.md and LICENSE.lightdash files.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


Scalar = str | int | float | bool | None
LogicalType = Literal["string", "number", "boolean", "date", "timestamp"]
FilterOperator = Literal[
    "equals",
    "isNull",
    "notNull",
    "inBetween",
    "inThePast",
    "inTheCurrent",
    "inPeriodToDate",
]


class FilterSettings(ContractModel):
    unitOfTime: Literal["days", "weeks", "months", "quarters", "years"] | None = None
    completed: bool | None = None


class FieldTarget(ContractModel):
    fieldId: str = Field(min_length=1)


class DashboardFieldTarget(FieldTarget):
    tableName: str = Field(min_length=1)
    isSqlColumn: bool | None = None


class FilterRule(ContractModel):
    id: str = Field(min_length=1)
    operator: FilterOperator
    values: list[Scalar] | None = None
    target: FieldTarget
    settings: FilterSettings | None = None


class AndFilterGroup(ContractModel):
    id: str = Field(min_length=1)
    and_: list[FilterGroup | FilterRule] = Field(alias="and")


class OrFilterGroup(ContractModel):
    id: str = Field(min_length=1)
    or_: list[FilterGroup | FilterRule] = Field(alias="or")


FilterGroup = Annotated[AndFilterGroup | OrFilterGroup, Field(union_mode="left_to_right")]


class DashboardFilterRule(ContractModel):
    id: str = Field(min_length=1)
    operator: FilterOperator
    values: list[Scalar] | None = None
    target: DashboardFieldTarget
    tileTargets: dict[str, DashboardFieldTarget | Literal[False]] | None = None
    label: str | None = None
    singleValue: bool | None = None
    required: bool | None = None
    disabled: bool | None = None
    settings: FilterSettings | None = None


class DashboardFilters(ContractModel):
    dimensions: list[DashboardFilterRule]
    metrics: list[DashboardFilterRule]


class QueryFilters(ContractModel):
    dimensions: FilterGroup | None = None
    metrics: FilterGroup | None = None


class SortField(ContractModel):
    fieldId: str = Field(min_length=1)
    descending: bool
    nullsFirst: bool | None = None


class SemanticChartQuery(ContractModel):
    kind: Literal["semantic"]
    exploreName: str = Field(min_length=1)
    dimensions: list[str]
    metrics: list[str] = Field(min_length=1)
    filters: QueryFilters
    sorts: list[SortField]
    limit: int = Field(ge=1, le=10_000)
    timezone: str | None = None
    pivotDimensions: list[str] | None = Field(default=None, max_length=1)
    projectId: str = Field(min_length=1)
    commitSha: str = Field(min_length=7)


class CustomFilterBinding(ContractModel):
    dashboardFieldId: str = Field(min_length=1)
    outputColumn: str = Field(min_length=1)
    logicalType: LogicalType


class ParameterDefinition(ContractModel):
    name: str = Field(min_length=1)
    logicalType: LogicalType
    nullable: bool


class AdHocSqlQuery(ContractModel):
    kind: Literal["sql"]
    connectionName: str = Field(min_length=1)
    sqlTemplate: str = Field(min_length=1)
    parameterDefinitions: list[ParameterDefinition]
    outputBindings: list[CustomFilterBinding]
    limit: int = Field(ge=1, le=10_000)


class KpiConfig(ContractModel):
    field: str = Field(min_length=1)
    format: str | None = None

    @model_validator(mode="after")
    def validate_format(self) -> KpiConfig:
        if self.format is None or self.format in {"integer", "decimal", "compact", "percentage"}:
            return self
        if self.format.startswith("currency:") and len(self.format) == 12 and self.format[9:].isupper():
            return self
        raise ValueError("format must be a supported format or currency:AAA")


class KpiChartConfig(ContractModel):
    type: Literal["big_number"]
    config: KpiConfig


class TableConfig(ContractModel):
    columns: list[str] = Field(min_length=1)
    groups: list[str] | None = None


class TableChartConfig(ContractModel):
    type: Literal["table"]
    config: TableConfig


class CartesianLayout(ContractModel):
    xField: str = Field(min_length=1)
    yField: list[str] = Field(min_length=1)
    stack: bool | None = None


class CartesianConfig(ContractModel):
    seriesType: Literal["bar", "line", "area"]
    layout: CartesianLayout


class CartesianChartConfig(ContractModel):
    type: Literal["cartesian"]
    config: CartesianConfig


Visualization = Annotated[
    KpiChartConfig | TableChartConfig | CartesianChartConfig,
    Field(discriminator="type"),
]
Query = Annotated[SemanticChartQuery | AdHocSqlQuery, Field(discriminator="kind")]


class ChartSignalPilot(ContractModel):
    crossFilter: bool
    drillDimensions: list[str] | None = None
    tableGroups: list[str] | None = None
    customFilterBindings: list[CustomFilterBinding] | None = None
    provenanceRef: str = Field(min_length=1)


class ChartDefinition(ContractModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = None
    query: Query
    visualization: Visualization
    signalPilot: ChartSignalPilot

    @model_validator(mode="after")
    def validate_encodings(self) -> ChartDefinition:
        outputs = (
            {*self.query.dimensions, *self.query.metrics}
            if isinstance(self.query, SemanticChartQuery)
            else {binding.outputColumn for binding in self.query.outputBindings}
        )
        if isinstance(self.visualization, KpiChartConfig):
            encoded = [self.visualization.config.field]
        elif isinstance(self.visualization, TableChartConfig):
            encoded = self.visualization.config.columns
        else:
            encoded = [
                self.visualization.config.layout.xField,
                *self.visualization.config.layout.yField,
            ]
        missing = [field for field in encoded if field not in outputs]
        if missing:
            raise ValueError(f"encoding references unknown query fields: {missing}")
        return self


class DashboardTileProperties(ContractModel):
    title: str | None = None
    hideTitle: bool | None = None
    chartName: str | None = None
    chartSlug: str = Field(min_length=1)


class DashboardTileDefinition(ContractModel):
    uuid: str = Field(min_length=1)
    tileSlug: str = Field(min_length=1)
    type: Literal["saved_chart"]
    x: int = Field(ge=0, le=35)
    y: int = Field(ge=0)
    h: int = Field(ge=1)
    w: int = Field(ge=1, le=36)
    properties: DashboardTileProperties
    chartId: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_grid_bounds(self) -> DashboardTileDefinition:
        if self.x + self.w > 36:
            raise ValueError("tile exceeds the 36-column grid")
        return self


class EvalBinding(ContractModel):
    chartId: str = Field(min_length=1)
    evalId: str = Field(min_length=1)


class DashboardSignalPilot(ContractModel):
    dashboardId: str = Field(min_length=1)
    projectId: str = Field(min_length=1)
    connectionName: str = Field(min_length=1)
    commitSha: str = Field(min_length=7)
    semanticFingerprint: str = Field(min_length=1)
    forkedFromVersionId: str | None = None
    evalBindings: list[EvalBinding] | None = None
    timezone: str = Field(min_length=1)


class DashboardDefinition(ContractModel):
    schemaVersion: Literal[1]
    name: str = Field(min_length=1)
    description: str | None = None
    filters: DashboardFilters
    tiles: list[DashboardTileDefinition] = Field(min_length=1)
    charts: list[ChartDefinition] = Field(min_length=1)
    signalPilot: DashboardSignalPilot

    @model_validator(mode="after")
    def validate_references(self) -> DashboardDefinition:
        chart_ids = [chart.id for chart in self.charts]
        tile_ids = [tile.uuid for tile in self.tiles]
        if len(chart_ids) != len(set(chart_ids)):
            raise ValueError("chart IDs must be unique")
        if len(tile_ids) != len(set(tile_ids)):
            raise ValueError("tile IDs must be unique")
        missing = [tile.chartId for tile in self.tiles if tile.chartId not in chart_ids]
        if missing:
            raise ValueError(f"tiles reference unknown charts: {missing}")
        return self


def normalize_dashboard_definition(definition: DashboardDefinition | dict) -> dict:
    parsed = (
        definition if isinstance(definition, DashboardDefinition) else DashboardDefinition.model_validate(definition)
    )
    return parsed.model_dump(mode="json", by_alias=True, exclude_none=True)


def dashboard_content_hash(definition: DashboardDefinition | dict) -> str:
    normalized = normalize_dashboard_definition(definition)
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


AndFilterGroup.model_rebuild()
OrFilterGroup.model_rebuild()
