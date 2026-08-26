export type DashboardLogicalType =
  | "string"
  | "number"
  | "boolean"
  | "date"
  | "timestamp"
  | "unknown";

export type DashboardResultColumn = {
  name: string;
  logicalType: DashboardLogicalType;
  nullable: boolean;
  label?: string;
  format?: DashboardValueFormat;
  currencyCode?: string;
};

export type DashboardValueFormat =
  | "integer"
  | "decimal"
  | "compact"
  | "percentage"
  | `currency:${string}`;

export type DashboardFailureCode =
  | "data_source_unavailable"
  | "authentication_rejected"
  | "query_timeout"
  | "query_invalid"
  | "semantic_definition_invalid"
  | "permission_denied"
  | "rate_limited"
  | "cancelled"
  | "result_contract_mismatch"
  | "stale_dashboard_version"
  | "internal_error";

export type DashboardFailure = {
  code: DashboardFailureCode;
  message: string;
  retryable: boolean;
  connectionName?: string;
  scope: "connection" | "chart" | "dashboard";
  correlationId: string;
  occurredAt: string;
  cacheFallbackAvailable: boolean;
  cacheState?: "no_usable_cache";
  retryAfterSeconds?: number;
};

export type DashboardResultState =
  | "fresh"
  | "stale_refreshing"
  | "cached_source_unavailable"
  | "cached_after_refresh_failure";

export type DashboardQueryResult = {
  resultId: string;
  executionId: string;
  columns: DashboardResultColumn[];
  rows: Record<string, unknown>[];
  completeness: "complete" | "truncated" | "unknown";
  freshnessAt: string;
  timezone: string;
  locale: string;
  cacheState?: DashboardResultState;
  refreshFailure?: DashboardFailure;
};

import type {
  ChartDefinition,
  DashboardDefinition,
  DashboardFilterRule,
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
  dashboardFilters?: DashboardRuntimeFilter[];
  dashboardDrillPath?: DashboardDrillStep[];
  invalidateCache?: boolean;
  retryToken?: string;
};

export type DashboardRuntimeFilter = {
  id: string;
  operator: DashboardFilterRule["operator"];
  values?: Array<string | number | boolean | null>;
  settings?: DashboardFilterRule["settings"];
};

export type DashboardDrillStep = {
  fieldId: string;
  value: string | number | boolean | null;
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
  format?: DashboardValueFormat;
  currencyCode?: string;
};

export type LightdashCartesianInput = {
  chartType: "cartesian";
  seriesType: "bar" | "line" | "area";
  xField: string;
  yFields: string[];
  rows: LightdashResultRow[];
  fields: Record<string, LightdashField>;
  locale: string;
  timezone: string;
};

export type DashboardRuntimeDefinition = DashboardDefinition;
