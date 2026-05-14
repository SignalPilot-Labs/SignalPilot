import type { ChartDefinitionV1 } from "@/lib/charts/types";
import type { ChartResponse, ChartRunResponse } from "@/lib/api/types";
import { mapToEChartsOption } from "@/lib/echarts/map-option";

// ── View-model ────────────────────────────────────────────────────────────────

export type ChartPreview =
  | { kind: "echart"; option: Record<string, unknown>; ariaLabel: string }
  | { kind: "table"; columns: { name: string; type: string }[]; rows: unknown[][]; caption: string }
  | { kind: "kpi"; label: string; value: number | null };

// ── Seed helper (deterministic, stable across reloads) ────────────────────────

function stableHash(id: string): number {
  const raw = [...id].reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 0);
  return Math.abs(raw);
}

// ── Sample-row builders ───────────────────────────────────────────────────────

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"] as const;

function buildEchartRun(seed: number, type: "bar" | "line"): ChartRunResponse {
  const rows: unknown[][] =
    type === "bar"
      ? MONTHS.map((_, i) => [MONTHS[i], (seed + i * 37) % 100])
      : MONTHS.map((_, i) => [MONTHS[i], (seed + i * 37) % 100, (seed + i * 53) % 100]);

  const columns: { name: string; type: string }[] =
    type === "bar"
      ? [{ name: "month", type: "string" }, { name: "value", type: "number" }]
      : [
          { name: "month", type: "string" },
          { name: "series_a", type: "number" },
          { name: "series_b", type: "number" },
        ];

  return {
    chart_id: "sample",
    cache_key: "",
    cached: false,
    computed_at: new Date(0).toISOString(),
    columns,
    rows,
    truncated: false,
  };
}

function buildTableRun(seed: number): { columns: { name: string; type: string }[]; rows: unknown[][] } {
  const columns = [
    { name: "id", type: "integer" },
    { name: "name", type: "string" },
    { name: "value", type: "integer" },
  ];
  const rows: unknown[][] = Array.from({ length: 10 }, (_, i) => [
    i + 1,
    `row-${i}`,
    (seed + i * 17) % 1000,
  ]);
  return { columns, rows };
}

function buildKpiValue(seed: number): number {
  return seed % 10000;
}

// ── Synthesis helper for echart path ─────────────────────────────────────────

function buildEchartPreview(
  def: ChartDefinitionV1,
  type: "bar" | "line"
): { kind: "echart"; option: Record<string, unknown>; ariaLabel: string } {
  const seed = stableHash(def.id);
  const chart: ChartResponse = {
    id: def.id,
    workspace_id: "sample",
    title: def.name,
    chart_type: type,
    echarts_option_json: {},
    created_at: def.createdAt,
    updated_at: def.createdAt,
    created_by: null,
    query: null,
  };
  const run = buildEchartRun(seed, type);
  const option = mapToEChartsOption(chart, run);
  return { kind: "echart", option, ariaLabel: `${def.name} ${type} chart (sample data)` };
}

// ── Main export ───────────────────────────────────────────────────────────────

export function buildSamplePreview(def: ChartDefinitionV1): ChartPreview {
  const seed = stableHash(def.id);

  switch (def.type) {
    case "bar":
      return buildEchartPreview(def, "bar");
    case "line":
      return buildEchartPreview(def, "line");
    case "table": {
      const { columns, rows } = buildTableRun(seed);
      return { kind: "table", columns, rows, caption: `${def.name} (sample data)` };
    }
    case "kpi": {
      const value = buildKpiValue(seed);
      return { kind: "kpi", label: def.name, value };
    }
    default: {
      // Exhaustiveness guard — def.type outside CHART_TYPES is a bug
      const exhaustiveCheck: never = def.type;
      throw new Error(`Unknown chart type: ${String(exhaustiveCheck)}`);
    }
  }
}
