export type DashboardLogicalType =
  "string" | "number" | "boolean" | "date" | "timestamp" | "unknown";

export type DashboardResultColumn = {
  name: string;
  logicalType: DashboardLogicalType;
  nullable: boolean;
  label?: string;
};

export type DashboardQueryResult = {
  resultId: string;
  executionId: string;
  columns: DashboardResultColumn[];
  rows: Record<string, unknown>[];
  completeness: "complete" | "truncated" | "unknown";
  freshnessAt: string;
};

import type {
  ChartDefinition,
  DashboardDefinition,
  DashboardTileDefinition,
} from "~/dashboard/lightdash-contract";

export type {
  AdHocSqlQuery,
  CartesianChartConfig,
  ChartDefinition,
  CustomFilterBinding,
  DashboardChartConfig,
  DashboardDefinition,
  DashboardFilterRule,
  DashboardFilters,
  DashboardTileDefinition,
  DashboardVersion,
  FilterGroup,
  KpiChartConfig,
  SemanticChartQuery,
  SortField,
  TableChartConfig,
} from "~/dashboard/lightdash-contract";

export type DashboardFilter = {
  field: string;
  operator: "equals";
  value: unknown;
  temporary?: boolean;
};

export type DashboardQueryOptions = {
  filters: DashboardFilter[];
  drillPath: Array<{ field: string; value: unknown }>;
};

export type DashboardChartReference = {
  dashboardUuid: string;
  dashboardVersionId: string;
  tileUuid: string;
  chartUuid: string;
  dashboardResultId: string;
  executionId: string;
  dashboardFilters: Record<string, unknown>;
  drillPath: Array<{ field: string; value: unknown }>;
  selectedMark: Record<string, unknown>;
  provenanceRef: string;
};

export type DashboardDataSource = {
  loadTile(
    tile: DashboardTileDefinition,
    chart: ChartDefinition,
    options: DashboardQueryOptions,
    signal: AbortSignal,
  ): Promise<DashboardQueryResult>;
};

export type LightdashResultValue = {
  raw: unknown;
  formatted: string;
};

export type LightdashResultRow = Record<
  string,
  { value: LightdashResultValue }
>;

export type LightdashField = {
  fieldId: string;
  label: string;
  type: DashboardLogicalType;
  role: "dimension" | "metric";
};

export type LightdashCartesianInput = {
  chartType: "cartesian";
  seriesType: "bar" | "line" | "area";
  xField: string;
  yFields: string[];
  rows: LightdashResultRow[];
  fields: Record<string, LightdashField>;
};

export type DashboardRuntimeDefinition = DashboardDefinition;
