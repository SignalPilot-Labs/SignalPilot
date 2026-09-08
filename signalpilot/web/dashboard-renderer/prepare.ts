/**
 * Row preparation and chart checks. Must stay behaviorally identical to the
 * Python implementation in notebook-server (see CONTRACTS "Row preparation"
 * and "Chart checks").
 *
 * Print-path module: relative imports only, no React, no DOM.
 */
import type { DatasetRows } from "./datasets";
import { isIsoDate, isNumeric, parseIsoDate, toNumber } from "./format";
import type { DashboardChart, DashboardFilter, DashboardSpec } from "./schema";
import { isCartesianChart } from "./schema";

export type ChartIssueCode =
  | "missing_dataset"
  | "dataset_unreadable"
  | "empty_dataset"
  | "missing_column"
  | "non_numeric_y"
  | "unparseable_date"
  | "too_many_rows"
  | "series_with_multi_y"
  | "unknown_chart";

export type ChartIssue = { code: ChartIssueCode | string; message: string };

export type FilterState = Record<string, unknown>;

const MAX_ROWS = 50000;
const COLUMN_SAMPLE_ROWS = 50;
const NUMERIC_THRESHOLD = 0.9;

const FAILING_CODES = new Set<string>([
  "missing_dataset",
  "dataset_unreadable",
  "missing_column",
  "series_with_multi_y",
]);

export function chartIsFailed(issues: ChartIssue[]): boolean {
  return issues.some((issue) => FAILING_CODES.has(issue.code));
}

/** Union of keys across the first 50 rows. */
function availableColumns(rows: DatasetRows): string[] {
  const seen = new Set<string>();
  for (const row of rows.slice(0, COLUMN_SAMPLE_ROWS)) {
    for (const key of Object.keys(row)) seen.add(key);
  }
  return [...seen];
}

/** Every column the chart references, in a stable order, de-duplicated. */
function referencedColumns(
  chart: DashboardChart,
  spec: DashboardSpec,
): string[] {
  const columns: string[] = [];
  switch (chart.type) {
    case "kpi":
      columns.push(chart.value.column);
      if (chart.comparison) columns.push(chart.comparison.column);
      break;
    case "table":
      columns.push(...chart.columns.map((column) => column.column));
      break;
    case "bar":
    case "line":
    case "area":
      columns.push(chart.x.column, ...chart.y.map((series) => series.column));
      if (chart.series) columns.push(chart.series.column);
      break;
    case "pie":
      columns.push(chart.label, chart.value.column);
      break;
    case "scatter":
      columns.push(chart.x.column, chart.y.column);
      if (chart.size) columns.push(chart.size);
      if (chart.color) columns.push(chart.color);
      break;
  }
  if (chart.sort) columns.push(chart.sort.column);
  for (const filter of spec.filters ?? []) {
    if (filter.dataset === chart.dataset) columns.push(filter.column);
  }
  return [...new Set(columns)];
}

/** Numeric (y/value) columns subject to the non_numeric_y check. */
function numericColumns(chart: DashboardChart): string[] {
  switch (chart.type) {
    case "kpi":
      return [chart.value.column];
    case "pie":
      return [chart.value.column];
    case "scatter":
      return [chart.y.column];
    case "bar":
    case "line":
    case "area":
      return chart.y.map((series) => series.column);
    default:
      return [];
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function filterValue(filter: DashboardFilter, filterState?: FilterState): unknown {
  if (filterState && Object.prototype.hasOwnProperty.call(filterState, filter.id)) {
    return filterState[filter.id];
  }
  return filter.default;
}

function applyFilter(
  rows: DatasetRows,
  filter: DashboardFilter,
  value: unknown,
): DatasetRows {
  const column = filter.column;
  switch (filter.type) {
    case "equals": {
      // Only a missing value disables the filter; "" is a real value to match.
      if (value === null || value === undefined) return rows;
      const wanted = String(value);
      return rows.filter((row) => String(row[column]) === wanted);
    }
    case "in": {
      if (!Array.isArray(value) || value.length === 0) return rows;
      const wanted = new Set(value.map(String));
      return rows.filter((row) => wanted.has(String(row[column])));
    }
    case "date_range": {
      if (!isRecord(value)) return rows;
      const from = parseIsoDate(value.from);
      const to = parseIsoDate(value.to);
      if (from === undefined && to === undefined) return rows;
      return rows.filter((row) => {
        const timestamp = parseIsoDate(row[column]);
        if (timestamp === undefined) return false;
        if (from !== undefined && timestamp < from) return false;
        if (to !== undefined && timestamp > to) return false;
        return true;
      });
    }
    case "number_range": {
      if (!isRecord(value)) return rows;
      const min = toNumber(value.min);
      const max = toNumber(value.max);
      if (min === undefined && max === undefined) return rows;
      return rows.filter((row) => {
        const numeric = toNumber(row[column]);
        if (numeric === undefined) return false;
        if (min !== undefined && numeric < min) return false;
        if (max !== undefined && numeric > max) return false;
        return true;
      });
    }
    default:
      return rows;
  }
}

function compareCells(left: unknown, right: unknown): number {
  const leftNull = left === null || left === undefined;
  const rightNull = right === null || right === undefined;
  if (leftNull && rightNull) return 0;
  if (leftNull) return 1;
  if (rightNull) return -1;
  const leftNumber = toNumber(left);
  const rightNumber = toNumber(right);
  if (leftNumber !== undefined && rightNumber !== undefined) {
    return leftNumber - rightNumber;
  }
  const leftText = String(left);
  const rightText = String(right);
  return leftText < rightText ? -1 : leftText > rightText ? 1 : 0;
}

export function sortRows(
  rows: DatasetRows,
  column: string,
  direction: "asc" | "desc" = "asc",
): DatasetRows {
  const sign = direction === "desc" ? -1 : 1;
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => {
      const aNull = a.row[column] === null || a.row[column] === undefined;
      const bNull = b.row[column] === null || b.row[column] === undefined;
      // Nulls last regardless of direction.
      if (aNull !== bNull) return aNull ? 1 : -1;
      const order = compareCells(a.row[column], b.row[column]) * sign;
      return order !== 0 ? order : a.index - b.index;
    })
    .map((entry) => entry.row);
}

/**
 * Share of non-null cells that pass `test`. Empty strings are non-null cells
 * that fail the numeric and date parsers, matching the Python `_ratio`.
 */
function ratioPassing(rows: DatasetRows, column: string, test: (v: unknown) => boolean) {
  let total = 0;
  let passing = 0;
  for (const row of rows) {
    const value = row[column];
    if (value === null || value === undefined) continue;
    total += 1;
    if (test(value)) passing += 1;
  }
  return { total, passing, ok: total === 0 || passing / total >= NUMERIC_THRESHOLD };
}

export type PreparedChart = { rows: DatasetRows; issues: ChartIssue[] };

/**
 * Apply filters (default or live state), sort, limit and the row cap, then run
 * the column and type checks. Never throws.
 */
export function prepareChartRows(
  chart: DashboardChart,
  spec: DashboardSpec,
  datasets: Record<string, DatasetRows>,
  filterState?: FilterState,
): PreparedChart {
  const issues: ChartIssue[] = [];
  const id = chart.id;
  const datasetName = chart.dataset;

  if (!Object.prototype.hasOwnProperty.call(spec.datasets, datasetName)) {
    issues.push({
      code: "missing_dataset",
      message: `Chart "${id}" references dataset "${datasetName}" which is not defined in datasets. Defined datasets: ${Object.keys(spec.datasets).join(", ") || "(none)"}.`,
    });
    return { rows: [], issues };
  }
  const source = datasets[datasetName];
  if (!Array.isArray(source)) {
    const file = spec.datasets[datasetName]?.file;
    issues.push({
      code: "dataset_unreadable",
      message: `Chart "${id}": dataset "${datasetName}"${file ? ` (${file})` : ""} could not be read.`,
    });
    return { rows: [], issues };
  }

  if (isCartesianChart(chart) && chart.series && chart.y.length > 1) {
    issues.push({
      code: "series_with_multi_y",
      message: `Chart "${id}": "series" (column "${chart.series.column}") requires exactly one y entry, but y has ${chart.y.length} entries.`,
    });
  }

  if (source.length > 0) {
    const available = availableColumns(source);
    const availableSet = new Set(available);
    for (const column of referencedColumns(chart, spec)) {
      if (!availableSet.has(column)) {
        issues.push({
          code: "missing_column",
          message: `Chart "${id}": column "${column}" not found in dataset "${datasetName}". Available columns: ${available.join(", ")}.`,
        });
      }
    }
  }
  if (chartIsFailed(issues)) return { rows: [], issues };

  let rows = source;
  for (const filter of spec.filters ?? []) {
    if (filter.dataset !== datasetName) continue;
    rows = applyFilter(rows, filter, filterValue(filter, filterState));
  }
  if (chart.sort) rows = sortRows(rows, chart.sort.column, chart.sort.direction ?? "asc");
  if (chart.limit !== undefined) rows = rows.slice(0, chart.limit);
  if (rows.length > MAX_ROWS) {
    issues.push({
      code: "too_many_rows",
      message: `Chart "${id}": dataset "${datasetName}" has ${rows.length} rows after preparation; only the first ${MAX_ROWS} are used.`,
    });
    rows = rows.slice(0, MAX_ROWS);
  }
  if (rows.length === 0) {
    issues.push({
      code: "empty_dataset",
      message: `Chart "${id}": dataset "${datasetName}" has no rows after filters.`,
    });
    return { rows, issues };
  }

  for (const column of numericColumns(chart)) {
    const check = ratioPassing(rows, column, isNumeric);
    if (!check.ok) {
      issues.push({
        code: "non_numeric_y",
        message: `Chart "${id}": column "${column}" in dataset "${datasetName}" is not numeric (${check.passing} of ${check.total} non-null values parse as numbers).`,
      });
    }
  }
  if ((isCartesianChart(chart) || chart.type === "scatter") && chart.x.type === "date") {
    const column = chart.x.column;
    const check = ratioPassing(rows, column, isIsoDate);
    if (!check.ok) {
      issues.push({
        code: "unparseable_date",
        message: `Chart "${id}": x column "${column}" in dataset "${datasetName}" has values that are not ISO dates (${check.passing} of ${check.total} non-null values parse as YYYY-MM-DD or ISO datetime).`,
      });
    }
  }
  return { rows, issues };
}

export function unknownChartIssue(chartId: string, spec: DashboardSpec): ChartIssue {
  return {
    code: "unknown_chart",
    message: `Chart "${chartId}" is not defined in this dashboard. Valid ids: ${spec.charts.map((chart) => chart.id).join(", ")}.`,
  };
}
