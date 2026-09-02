/*
 * Adapted from Lightdash at b91bd2273f38fdc58702c71f538b6b5d5ae462c5.
 * See ../LICENSE.lightdash and ../CONTRACT_MAPPING.md.
 */

export type DashboardTileType = "saved_chart";

export type DashboardTileDefinition = {
  uuid: string;
  tileSlug: string;
  type: DashboardTileType;
  x: number;
  y: number;
  h: number;
  w: number;
  properties: {
    title?: string;
    hideTitle?: boolean;
    chartName?: string | null;
    chartSlug: string;
    sectionTitle?: string;
  };
  chartId: string;
};

export type DashboardFieldTarget = {
  fieldId: string;
  tableName: string;
  isSqlColumn?: boolean;
};

export type DashboardFilterOperator =
  | "equals"
  | "isNull"
  | "notNull"
  | "inBetween"
  | "inThePast"
  | "inTheCurrent"
  | "inPeriodToDate";

export type DashboardFilterRule = {
  id: string;
  operator: DashboardFilterOperator;
  values?: Array<string | number | boolean | null>;
  target: DashboardFieldTarget;
  tileTargets?: Record<string, DashboardFieldTarget | false>;
  label?: string;
  singleValue?: boolean;
  required?: boolean;
  disabled?: boolean;
  settings?: {
    unitOfTime?: "days" | "weeks" | "months" | "quarters" | "years";
    completed?: boolean;
  };
};

export type DashboardFilters = {
  dimensions: DashboardFilterRule[];
  metrics: DashboardFilterRule[];
};

export type FilterRule = {
  id: string;
  operator: DashboardFilterOperator;
  values?: Array<string | number | boolean | null>;
  target: { fieldId: string };
  settings?: DashboardFilterRule["settings"];
};

export type FilterGroup =
  | { id: string; and: Array<FilterGroup | FilterRule> }
  | { id: string; or: Array<FilterGroup | FilterRule> };

export type SortField = {
  fieldId: string;
  descending: boolean;
  nullsFirst?: boolean;
};

export type SemanticChartQuery = {
  kind: "semantic";
  exploreName: string;
  dimensions: string[];
  metrics: string[];
  filters: {
    dimensions?: FilterGroup;
    metrics?: FilterGroup;
  };
  sorts: SortField[];
  limit: number;
  timezone?: string;
  pivotDimensions?: string[];
  projectId: string;
  commitSha: string;
};

export type CustomFilterBinding = {
  dashboardFieldId: string;
  outputColumn: string;
  logicalType: "string" | "number" | "boolean" | "date" | "timestamp";
};

export type AdHocSqlQuery = {
  kind: "sql";
  connectionName: string;
  sqlTemplate: string;
  parameterDefinitions: Array<{
    name: string;
    logicalType: CustomFilterBinding["logicalType"];
    nullable: boolean;
  }>;
  outputBindings: CustomFilterBinding[];
  limit: number;
};

export type KpiChartConfig = {
  type: "big_number";
  config: {
    field: string;
    format?:
      | "integer"
      | "decimal"
      | "compact"
      | "percentage"
      | `currency:${string}`;
  };
};

export type TableChartConfig = {
  type: "table";
  config: { columns: string[]; groups?: string[] };
};

export type CartesianChartConfig = {
  type: "cartesian";
  config: {
    seriesType: "bar" | "line" | "area";
    layout: {
      xField: string;
      yField: string[];
      stack?: boolean;
    };
  };
};

export type DashboardChartConfig =
  | KpiChartConfig
  | TableChartConfig
  | CartesianChartConfig;

export type ChartDefinition = {
  id: string;
  title: string;
  question?: string;
  description?: string;
  query: SemanticChartQuery | AdHocSqlQuery;
  visualization: DashboardChartConfig;
  signalPilot: {
    crossFilter: boolean;
    drillDimensions?: string[];
    tableGroups?: string[];
    customFilterBindings?: CustomFilterBinding[];
    provenanceRef: string;
  };
};

export type DashboardDefinition = {
  schemaVersion: 1;
  name: string;
  description?: string;
  filters: DashboardFilters;
  tiles: DashboardTileDefinition[];
  charts: ChartDefinition[];
  signalPilot: {
    dashboardId: string;
    projectId: string;
    connectionName: string;
    commitSha: string;
    semanticFingerprint: string;
    forkedFromVersionId?: string;
    evalBindings?: Array<{
      chartId: string;
      evalId: string;
    }>;
    timezone: string;
  };
};

export type DashboardVersion = {
  versionId: string;
  dashboardId: string;
  number: number;
  definition: DashboardDefinition;
  contentHash: string;
  createdAt: string;
};

export type LightdashCompatibilityFixture = {
  dashboard: {
    name: string;
    description?: string;
    version: number;
    filters: DashboardFilters;
    tiles: DashboardTileDefinition[];
  };
  charts: ChartDefinition[];
  signalPilot: DashboardDefinition["signalPilot"];
};
