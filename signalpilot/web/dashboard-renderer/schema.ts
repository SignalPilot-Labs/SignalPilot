/**
 * Hand-written TypeScript mirror of `dashboard.schema.json` (the JSON Schema
 * is the source of truth; keep this file in sync) plus an ajv validator.
 *
 * Print-path module: relative imports only, no React, no DOM.
 */
import Ajv2020 from "ajv/dist/2020";
import type { ErrorObject, ValidateFunction } from "ajv";
import addFormats from "ajv-formats";

import dashboardSchema from "./dashboard.schema.json";

export type DashboardFormat =
  | "integer"
  | "decimal"
  | "compact"
  | "percentage"
  | `currency:${string}`;

export type DashboardCellValue = string | number | boolean | null;

export type DashboardSeries = {
  column: string;
  label?: string;
  format?: DashboardFormat;
};

export type DashboardAxisType = "category" | "date" | "number";

export type DashboardAxis = {
  column: string;
  label?: string;
  type?: DashboardAxisType;
};

export type DashboardSort = {
  column: string;
  direction?: "asc" | "desc";
};

export type DashboardGrid = { x: number; y: number; w: number; h: number };

/**
 * A dataset defined by one SQL query on a named connection. Its rows are
 * the query result; the chat renders the snapshot the sandbox helper wrote
 * at `artifacts/datasets/<name>.csv` (see `datasetSnapshotPath`).
 */
export type DashboardSqlDataset = { connection: string; sql: string };

/** Static rows for constants that never refresh. */
export type DashboardStaticDataset = {
  rows: Record<string, DashboardCellValue>[];
};

export type DashboardDataset = DashboardSqlDataset | DashboardStaticDataset;

export function isSqlDataset(dataset: DashboardDataset): dataset is DashboardSqlDataset {
  return "sql" in dataset;
}

export type DashboardFilterType =
  | "equals"
  | "in"
  | "date_range"
  | "number_range";

export type DashboardFilter = {
  id: string;
  label: string;
  dataset: string;
  column: string;
  type: DashboardFilterType;
  default?: unknown;
};

type ChartBase = {
  id: string;
  title: string;
  description?: string;
  dataset: string;
  sort?: DashboardSort;
  limit?: number;
  grid?: DashboardGrid;
};

export type KpiChart = ChartBase & {
  type: "kpi";
  value: DashboardSeries;
  comparison?: DashboardSeries;
};

export type TableChart = ChartBase & {
  type: "table";
  columns: DashboardSeries[];
};

export type CartesianChartType = "bar" | "line" | "area";

export type CartesianChart = ChartBase & {
  type: CartesianChartType;
  x: DashboardAxis;
  y: DashboardSeries[];
  series?: { column: string; stack?: boolean };
  stack?: boolean;
  horizontal?: boolean;
};

export type PieChart = ChartBase & {
  type: "pie";
  label: string;
  value: DashboardSeries;
  donut?: boolean;
};

export type ScatterChart = ChartBase & {
  type: "scatter";
  x: DashboardAxis;
  y: DashboardSeries;
  size?: string;
  color?: string;
};

export type DashboardChart =
  | KpiChart
  | TableChart
  | CartesianChart
  | PieChart
  | ScatterChart;

export type DashboardLayout = { columns?: 12; rowHeight?: number };

export type DashboardSpec = {
  $schema?: string;
  version: 1;
  title: string;
  description?: string;
  layout?: DashboardLayout;
  datasets: Record<string, DashboardDataset>;
  filters?: DashboardFilter[];
  charts: DashboardChart[];
};

export type ValidationResult =
  | { ok: true; spec: DashboardSpec }
  | { ok: false; errors: string[] };

let compiled: ValidateFunction | undefined;

function validator(): ValidateFunction {
  if (compiled) return compiled;
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  compiled = ajv.compile(dashboardSchema as object);
  return compiled;
}

function describeError(error: ErrorObject): string {
  const path = error.instancePath || "/";
  const message = error.message ?? "is invalid";
  const extra =
    error.keyword === "additionalProperties" &&
    typeof error.params?.additionalProperty === "string"
      ? ` ("${error.params.additionalProperty}")`
      : error.keyword === "enum" && Array.isArray(error.params?.allowedValues)
        ? ` (${(error.params.allowedValues as unknown[]).map(String).join(", ")})`
        : "";
  return `${path} ${message}${extra}`;
}

/**
 * Validate an arbitrary value against the dashboard JSON schema. Error strings
 * are `<instancePath or "/"> <message>`, de-duplicated, in schema order.
 */
export function validateDashboardSpec(input: unknown): ValidationResult {
  if (input === null || typeof input !== "object" || Array.isArray(input)) {
    return { ok: false, errors: ["/ must be object"] };
  }
  const validate = validator();
  if (validate(input)) return { ok: true, spec: input as DashboardSpec };
  const seen = new Set<string>();
  const errors: string[] = [];
  for (const error of validate.errors ?? []) {
    const text = describeError(error);
    if (seen.has(text)) continue;
    seen.add(text);
    errors.push(text);
  }
  return { ok: false, errors: errors.length ? errors : ["/ is invalid"] };
}

export function isCartesianChart(chart: DashboardChart): chart is CartesianChart {
  return chart.type === "bar" || chart.type === "line" || chart.type === "area";
}
