import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { validateDashboardSpec } from "./schema";

const here = __dirname;
const pluginSchema = join(here, "..", "..", "..", "signalpilot-plugin", "skills", "dashboard", "dashboard.schema.json");
const localSchema = join(here, "dashboard.schema.json");

export function loadFixtureSpec(): unknown {
  return JSON.parse(readFileSync(join(here, "fixtures", "revenue.dashboard.json"), "utf8"));
}

describe("dashboard.schema.json", () => {
  it("is byte-identical to the plugin schema", () => {
    const plugin = readFileSync(pluginSchema);
    const local = readFileSync(localSchema);
    expect(local.equals(plugin)).toBe(true);
  });
});

describe("validateDashboardSpec", () => {
  it("accepts the revenue fixture", () => {
    const result = validateDashboardSpec(loadFixtureSpec());
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.spec.charts.map((chart) => chart.type)).toContain("scatter");
  });

  it("accepts a minimal spec with inline rows", () => {
    const result = validateDashboardSpec({
      version: 1,
      title: "T",
      datasets: { d: { rows: [{ a: 1 }] } },
      charts: [{ id: "k", type: "kpi", title: "K", dataset: "d", value: { column: "a" } }],
    });
    expect(result.ok).toBe(true);
  });

  it("rejects non-objects", () => {
    expect(validateDashboardSpec(null)).toEqual({ ok: false, errors: ["/ must be object"] });
    expect(validateDashboardSpec([])).toEqual({ ok: false, errors: ["/ must be object"] });
  });

  it("reports instance paths and messages", () => {
    const result = validateDashboardSpec({
      version: 2,
      title: "",
      datasets: {},
      charts: [],
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors).toContain("/version must be equal to constant");
    expect(result.errors).toContain("/title must NOT have fewer than 1 characters");
    expect(result.errors).toContain("/datasets must NOT have fewer than 1 properties");
    expect(result.errors).toContain("/charts must NOT have fewer than 1 items");
  });

  it("rejects unknown chart properties and bad ids", () => {
    const result = validateDashboardSpec({
      version: 1,
      title: "T",
      datasets: { d: { rows: [] } },
      charts: [{ id: "Bad-Id", type: "kpi", title: "K", dataset: "d", value: { column: "a" }, extra: 1 }],
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.some((error) => error.startsWith("/charts/0/id must match pattern"))).toBe(true);
    expect(result.errors.some((error) => error.includes('"extra"'))).toBe(true);
  });

  it("accepts combo and heatmap charts and rejects their bad shapes", () => {
    const withChart = (chart: unknown) =>
      validateDashboardSpec({ version: 1, title: "T", datasets: { d: { rows: [{ a: 1 }] } }, charts: [chart] });
    const combo = {
      id: "c", type: "combo", title: "C", dataset: "d",
      x: { column: "month", type: "date" },
      bars: [{ column: "revenue" }],
      lines: [{ column: "margin", format: "percentage" }],
      secondary_axis: true,
      stack: false,
    };
    const heatmap = {
      id: "h", type: "heatmap", title: "H", dataset: "d",
      x: { column: "month" }, y: { column: "region" }, value: { column: "revenue" }, show_values: true,
    };
    expect(withChart(combo).ok).toBe(true);
    expect(withChart(heatmap).ok).toBe(true);
    for (const bad of [
      { ...combo, lines: [] },
      { ...combo, bars: [1, 2, 3, 4, 5].map((n) => ({ column: "b" + n })) },
      { ...combo, y: [{ column: "x" }] },
      { ...heatmap, y: "region" },
      { ...heatmap, value: undefined },
      { ...heatmap, horizontal: true },
    ]) {
      expect(withChart(bad).ok).toBe(false);
    }
  });

  it("accepts a SQL dataset and rejects mixed or partial shapes", () => {
    const chart = { id: "k", type: "kpi", title: "K", dataset: "d", value: { column: "a" } };
    const withDataset = (dataset: unknown) =>
      validateDashboardSpec({ version: 1, title: "T", datasets: { d: dataset }, charts: [chart] });
    expect(withDataset({ connection: "warehouse", sql: "select 1 as a" }).ok).toBe(true);
    for (const dataset of [
      { connection: "warehouse", sql: "select 1", rows: [] },
      { sql: "select 1" },
      { connection: "warehouse" },
      { file: "artifacts/a.csv" },
      {},
    ]) {
      const result = withDataset(dataset);
      expect(result.ok).toBe(false);
      if (result.ok) return;
      expect(result.errors.some((error) => error.startsWith("/datasets/d must match exactly one schema"))).toBe(true);
    }
  });
});
