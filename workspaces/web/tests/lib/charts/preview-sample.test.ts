import { describe, it, expect } from "vitest";
import { buildSamplePreview } from "@/lib/charts/preview-sample";
import type { ChartDefinitionV1 } from "@/lib/charts/types";

function makeDef(overrides: Partial<ChartDefinitionV1> = {}): ChartDefinitionV1 {
  return {
    schemaVersion: 1,
    id: "aaaaaaaa-0000-4000-8000-aaaaaaaaaaaa",
    name: "Test Chart",
    type: "bar",
    sql: "SELECT 1",
    createdAt: "2024-01-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("buildSamplePreview", () => {
  it("bar def returns kind=echart with xAxis, yAxis, series", () => {
    const preview = buildSamplePreview(makeDef({ type: "bar" }));
    expect(preview.kind).toBe("echart");
    if (preview.kind !== "echart") return;
    expect(preview.option).toHaveProperty("xAxis");
    expect(preview.option).toHaveProperty("yAxis");
    expect(preview.option).toHaveProperty("series");
    const series = preview.option["series"] as { type: string }[];
    expect(series[0].type).toBe("bar");
  });

  it("line def returns kind=echart with xAxis, yAxis, series (2 series)", () => {
    const preview = buildSamplePreview(makeDef({ type: "line" }));
    expect(preview.kind).toBe("echart");
    if (preview.kind !== "echart") return;
    expect(preview.option).toHaveProperty("xAxis");
    expect(preview.option).toHaveProperty("yAxis");
    expect(preview.option).toHaveProperty("series");
    const series = preview.option["series"] as { type: string }[];
    expect(series).toHaveLength(2);
    expect(series[0].type).toBe("line");
  });

  it("table def returns kind=table with columns length>=1 and rows length===10", () => {
    const preview = buildSamplePreview(makeDef({ type: "table" }));
    expect(preview.kind).toBe("table");
    if (preview.kind !== "table") return;
    expect(preview.columns.length).toBeGreaterThanOrEqual(1);
    expect(preview.rows).toHaveLength(10);
  });

  it("kpi def returns kind=kpi with a numeric value", () => {
    const preview = buildSamplePreview(makeDef({ type: "kpi" }));
    expect(preview.kind).toBe("kpi");
    if (preview.kind !== "kpi") return;
    expect(typeof preview.value).toBe("number");
  });

  it("same id produces same numbers across calls (determinism)", () => {
    const def = makeDef({ type: "bar" });
    const p1 = buildSamplePreview(def);
    const p2 = buildSamplePreview(def);
    expect(p1).toEqual(p2);
  });

  it("different ids produce different kpi values (seed distinguishes charts)", () => {
    const p1 = buildSamplePreview(makeDef({ type: "kpi", id: "aaaaaaaa-0000-4000-8000-000000000001" }));
    const p2 = buildSamplePreview(makeDef({ type: "kpi", id: "aaaaaaaa-0000-4000-8000-000000000002" }));
    expect(p1).not.toEqual(p2);
  });

  it("animation is false in echart option (forced layer via mapToEChartsOption)", () => {
    const preview = buildSamplePreview(makeDef({ type: "bar" }));
    if (preview.kind !== "echart") throw new Error("expected echart");
    expect(preview.option["animation"]).toBe(false);
  });

  it("throws on unknown chart type (no silent fallback)", () => {
    const def = makeDef({ type: "unknown_type" as "bar" });
    expect(() => buildSamplePreview(def)).toThrow("Unknown chart type: unknown_type");
  });
});
