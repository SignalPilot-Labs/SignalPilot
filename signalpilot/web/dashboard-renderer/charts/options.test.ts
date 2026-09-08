// @vitest-environment node
import { describe, expect, it } from "vitest";

import type { DatasetRows } from "../datasets";
import type { CartesianChart, PieChart, ScatterChart } from "../schema";
import { LIGHT_THEME } from "../theme";
import { buildChartOption } from "./options";

const rows: DatasetRows = [
  { month: "2024-01-01", region: "North", revenue: 10, target: 12, customers: 100 },
  { month: "2024-01-01", region: "South", revenue: 20, target: 18, customers: 200 },
  { month: "2024-02-01", region: "North", revenue: 15, target: 12, customers: 110 },
  { month: "2024-02-01", region: "South", revenue: 25, target: 18, customers: 210 },
];

type AnyRecord = Record<string, unknown>;
const seriesOf = (option: unknown) => (option as { series: AnyRecord[] }).series;
const axis = (option: unknown, key: "xAxis" | "yAxis") => (option as Record<string, AnyRecord>)[key];

const base = { id: "c", title: "C", dataset: "d" };

describe("buildChartOption cartesian", () => {
  it("bar with two y columns on a category axis", () => {
    const chart: CartesianChart = {
      ...base,
      type: "bar",
      x: { column: "region", type: "category" },
      y: [{ column: "revenue", label: "Revenue" }, { column: "target" }],
    };
    const option = buildChartOption(chart, rows, "light");
    const series = seriesOf(option);
    expect(series).toHaveLength(2);
    expect(series.map((entry) => entry.type)).toEqual(["bar", "bar"]);
    expect(series.map((entry) => entry.name)).toEqual(["Revenue", "target"]);
    expect(series[0].stack).toBeUndefined();
    expect(axis(option, "xAxis").type).toBe("category");
    expect(axis(option, "xAxis").data).toEqual(["North", "South"]);
    expect(axis(option, "yAxis").type).toBe("value");
    expect((option as AnyRecord).legend).toMatchObject({ show: true, type: "plain" });
    expect(series[0].color).toBe(LIGHT_THEME.palette[0]);
  });

  it("stacked horizontal bar swaps axes", () => {
    const chart: CartesianChart = {
      ...base,
      type: "bar",
      horizontal: true,
      stack: true,
      x: { column: "region" },
      y: [{ column: "revenue" }, { column: "target" }],
    };
    const option = buildChartOption(chart, rows, "dark");
    expect(axis(option, "xAxis").type).toBe("value");
    expect(axis(option, "yAxis")).toMatchObject({ type: "category", inverse: true });
    expect(seriesOf(option).every((entry) => entry.stack === "total")).toBe(true);
  });

  it("line with series split on a time axis", () => {
    const chart: CartesianChart = {
      ...base,
      type: "line",
      x: { column: "month", type: "date" },
      y: [{ column: "revenue", format: "currency:USD" }],
      series: { column: "region", stack: true },
    };
    const option = buildChartOption(chart, rows, "light");
    const series = seriesOf(option);
    expect(series.map((entry) => entry.name)).toEqual(["North", "South"]);
    expect(series.map((entry) => entry.type)).toEqual(["line", "line"]);
    expect(series.every((entry) => entry.stack === "total")).toBe(true);
    expect(axis(option, "xAxis").type).toBe("time");
    const first = (series[0].data as { value: unknown }[])[0].value as [number, number];
    expect(first).toEqual([Date.UTC(2024, 0, 1), 10]);
    const formatter = (axis(option, "xAxis").axisLabel as { formatter: (v: number) => string }).formatter;
    expect(formatter(Date.UTC(2024, 0, 1))).toBe("Jan 2024");
    const yFormatter = (axis(option, "yAxis").axisLabel as { formatter: (v: number) => string }).formatter;
    expect(yFormatter(1500)).toBe("$1.5K");
  });

  it("area adds areaStyle and number x uses a value axis", () => {
    const chart: CartesianChart = {
      ...base,
      type: "area",
      x: { column: "customers", type: "number" },
      y: [{ column: "revenue" }],
    };
    const option = buildChartOption(chart, rows, "light");
    expect(seriesOf(option)[0].areaStyle).toBeDefined();
    expect(axis(option, "xAxis").type).toBe("value");
    expect((option as AnyRecord).legend).toMatchObject({ show: false });
  });

  it("tooltip formatter names the x value and each series", () => {
    const chart: CartesianChart = {
      ...base,
      type: "bar",
      x: { column: "region" },
      y: [{ column: "revenue", label: "Revenue", format: "integer" }],
    };
    const option = buildChartOption(chart, rows, "light");
    const formatter = ((option as AnyRecord).tooltip as { formatter: (p: unknown) => string }).formatter;
    const data = (seriesOf(option)[0].data as AnyRecord[])[0];
    expect(formatter([{ seriesName: "Revenue", data }])).toBe("North<br/>Revenue: 15");
  });
});

describe("buildChartOption pie", () => {
  it("builds one pie series with donut radius", () => {
    const chart: PieChart = { ...base, type: "pie", label: "region", value: { column: "revenue" }, donut: true };
    const option = buildChartOption(chart, rows.slice(0, 2), "light");
    const series = seriesOf(option);
    expect(series).toHaveLength(1);
    expect(series[0].type).toBe("pie");
    expect(series[0].radius).toEqual(["42%", "68%"]);
    expect((option as AnyRecord).legend).toMatchObject({ show: true, type: "plain", orient: "horizontal" });
    expect(series[0].data).toEqual([
      { name: "North", value: 10, rowIndex: 0 },
      { name: "South", value: 20, rowIndex: 1 },
    ]);
  });
});

describe("buildChartOption scatter", () => {
  it("splits by color column and scales symbol size", () => {
    const chart: ScatterChart = {
      ...base,
      type: "scatter",
      x: { column: "customers", type: "number" },
      y: { column: "revenue" },
      size: "target",
      color: "region",
    };
    const option = buildChartOption(chart, rows, "light");
    const series = seriesOf(option);
    expect(series.map((entry) => entry.name)).toEqual(["North", "South"]);
    expect(series.every((entry) => entry.type === "scatter")).toBe(true);
    const point = (series[0].data as { value: unknown[] }[])[0].value;
    expect(point).toEqual([100, 10, 12]);
    const symbolSize = series[0].symbolSize as (value: unknown[]) => number;
    expect(symbolSize([0, 0, 18])).toBeCloseTo(30);
    expect(symbolSize([0, 0, null])).toBe(8);
  });

  it("single series without color uses the y label and category x", () => {
    const chart: ScatterChart = { ...base, type: "scatter", x: { column: "region" }, y: { column: "revenue", label: "Rev" } };
    const option = buildChartOption(chart, rows, "light");
    expect(seriesOf(option)).toHaveLength(1);
    expect(seriesOf(option)[0].name).toBe("Rev");
    expect(axis(option, "xAxis").type).toBe("category");
  });
});
