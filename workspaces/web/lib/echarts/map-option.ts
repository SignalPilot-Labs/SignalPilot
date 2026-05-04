import type { ChartResponse, ChartRunResponse } from "@/lib/api/types";

/**
 * Deep-merge two plain objects. Arrays are replaced (not concatenated).
 * `b` wins on conflicts. Returns a new object.
 */
function deepMerge(
  a: Record<string, unknown>,
  b: Record<string, unknown>
): Record<string, unknown> {
  const result: Record<string, unknown> = { ...a };
  for (const key of Object.keys(b)) {
    const aVal = result[key];
    const bVal = b[key];
    if (
      bVal !== null &&
      typeof bVal === "object" &&
      !Array.isArray(bVal) &&
      aVal !== null &&
      typeof aVal === "object" &&
      !Array.isArray(aVal)
    ) {
      result[key] = deepMerge(
        aVal as Record<string, unknown>,
        bVal as Record<string, unknown>
      );
    } else {
      result[key] = bVal;
    }
  }
  return result;
}

const MAX_POINTS = 1000;

/**
 * Build an ECharts option object for a line or bar chart.
 *
 * Merge order (lowest → highest precedence):
 * 1. Derived default — from chart_type + run columns/rows
 * 2. Backend overlay — chart.echarts_option_json deep-merged over derived
 * 3. Forced layer — animation:false, tooltip.trigger:'axis', truncation graphic
 *    The forced layer always wins; backend cannot override it.
 */
export function mapToEChartsOption(
  chart: ChartResponse,
  run: ChartRunResponse
): Record<string, unknown> {
  const rows = run.rows.slice(0, MAX_POINTS);
  const columns = run.columns;

  // ── 1. Derived default ───────────────────────────────────────────────────
  const xData = rows.map((row) => {
    const val = row[0];
    return val == null ? "" : String(val);
  });

  const seriesColumns = columns.slice(1);
  const seriesType = chart.chart_type === "bar" ? "bar" : "line";

  const series = seriesColumns.map((col, idx) => ({
    name: col.name,
    type: seriesType,
    data: rows.map((row) => row[idx + 1] ?? null),
  }));

  const derived: Record<string, unknown> = {
    xAxis: {
      type: "category",
      data: xData,
    },
    yAxis: {
      type: "value",
    },
    series,
  };

  // ── 2. Backend overlay ───────────────────────────────────────────────────
  const overlay = chart.echarts_option_json ?? {};
  const merged = deepMerge(derived, overlay as Record<string, unknown>);

  // ── 3. Forced layer (always wins) ────────────────────────────────────────
  const forced: Record<string, unknown> = {
    animation: false,
    tooltip: deepMerge(
      typeof merged.tooltip === "object" && merged.tooltip !== null
        ? (merged.tooltip as Record<string, unknown>)
        : {},
      { trigger: "axis" }
    ),
  };

  if (run.truncated) {
    const existingGraphic = Array.isArray(merged.graphic)
      ? (merged.graphic as unknown[])
      : [];
    forced.graphic = [
      ...existingGraphic,
      {
        type: "text",
        right: 16,
        top: 4,
        style: {
          text: `Showing first ${MAX_POINTS} rows`,
          fontSize: 11,
          fill: "#6B7280",
        },
      },
    ];
  }

  return deepMerge(merged, forced);
}
