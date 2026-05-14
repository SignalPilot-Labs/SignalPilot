import { describe, it, expect } from "vitest";
import { mapToEChartsOption } from "@/lib/echarts/map-option";
import type { ChartResponse, ChartRunResponse } from "@/lib/api/types";

function makeChart(overrides: Partial<ChartResponse> = {}): ChartResponse {
  return {
    id: "chart-1",
    workspace_id: "ws-1",
    title: "Test Chart",
    chart_type: "line",
    echarts_option_json: {},
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    created_by: null,
    query: null,
    ...overrides,
  };
}

function makeRun(overrides: Partial<ChartRunResponse> = {}): ChartRunResponse {
  return {
    chart_id: "chart-1",
    cache_key: "k1",
    cached: false,
    computed_at: "2024-01-01T00:00:00Z",
    columns: [
      { name: "date", type: "string" },
      { name: "value", type: "number" },
    ],
    rows: [
      ["2024-01", 10],
      ["2024-02", 20],
    ],
    truncated: false,
    ...overrides,
  };
}

describe("mapToEChartsOption", () => {
  it("derives xAxis.data from col 0 and one line series from col 1 for chart_type=line", () => {
    const chart = makeChart({ chart_type: "line", echarts_option_json: {} });
    const run = makeRun();

    const option = mapToEChartsOption(chart, run);

    const xAxis = option["xAxis"] as { data: string[] };
    expect(xAxis.data).toEqual(["2024-01", "2024-02"]);

    const series = option["series"] as { type: string; data: unknown[] }[];
    expect(series).toHaveLength(1);
    expect(series[0].type).toBe("line");
    expect(series[0].data).toEqual([10, 20]);
  });

  it("preserves backend overlay title.text (overlay > derived)", () => {
    const chart = makeChart({
      chart_type: "bar",
      echarts_option_json: { title: { text: "My Override Title" } },
    });
    const run = makeRun();

    const option = mapToEChartsOption(chart, run);

    const title = option["title"] as { text: string };
    expect(title.text).toBe("My Override Title");

    const series = option["series"] as { type: string }[];
    expect(series[0].type).toBe("bar");
  });

  it("adds a graphic entry with text matching /first/i when run.truncated is true", () => {
    const chart = makeChart({ chart_type: "line", echarts_option_json: {} });
    const run = makeRun({ truncated: true });

    const option = mapToEChartsOption(chart, run);

    const graphic = option["graphic"] as { style?: { text?: string } }[];
    expect(Array.isArray(graphic)).toBe(true);
    const hasFirstNote = graphic.some(
      (g) => g.style?.text != null && /first/i.test(g.style.text)
    );
    expect(hasFirstNote).toBe(true);
  });

  it("forced layer overrides backend animation:true and tooltip.trigger:'item'", () => {
    const chart = makeChart({
      chart_type: "line",
      echarts_option_json: {
        animation: true,
        tooltip: { trigger: "item" },
      },
    });
    const run = makeRun();

    const option = mapToEChartsOption(chart, run);

    expect(option["animation"]).toBe(false);
    const tooltip = option["tooltip"] as { trigger: string };
    expect(tooltip.trigger).toBe("axis");
  });
});
