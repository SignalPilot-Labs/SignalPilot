// @vitest-environment node
import { describe, expect, it } from "vitest";

import type { DatasetRows } from "../datasets";
import type { CartesianChart, ComboChart, HeatmapChart, PieChart, ScatterChart } from "../schema";
import { LIGHT_THEME } from "../theme";
import { heatmapRange, mixHex } from "./heatmap";
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

describe("buildChartOption combo", () => {
  const combo: ComboChart = {
    ...base,
    type: "combo",
    x: { column: "month", type: "date" },
    bars: [{ column: "revenue", label: "Revenue", format: "currency:USD" }, { column: "target" }],
    lines: [{ column: "customers", label: "Customers", format: "integer" }],
  };

  it("draws bars on the left axis and lines on a right axis by default", () => {
    const option = buildChartOption(combo, rows, "light");
    const series = seriesOf(option);
    expect(series).toHaveLength(3);
    expect(series.map((entry) => entry.type)).toEqual(["bar", "bar", "line"]);
    expect(series.map((entry) => entry.yAxisIndex)).toEqual([0, 0, 1]);
    expect(series.map((entry) => entry.name)).toEqual(["Revenue", "target", "Customers"]);
    expect(series.every((entry) => entry.stack === undefined)).toBe(true);
    expect(series[2].color).toBe(LIGHT_THEME.palette[2]);
    const yAxes = axis(option, "yAxis") as unknown as AnyRecord[];
    expect(yAxes).toHaveLength(2);
    const left = (yAxes[0].axisLabel as { formatter: (v: number) => string }).formatter;
    const right = (yAxes[1].axisLabel as { formatter: (v: number) => string }).formatter;
    expect(left(1500)).toBe("$1.5K");
    expect(right(1500)).toBe("1.5K");
    expect(yAxes[1].splitLine).toEqual({ show: false });
    expect(axis(option, "xAxis").type).toBe("time");
    expect((option as AnyRecord).legend).toMatchObject({ show: true });
  });

  it("stacks bars and shares one axis when secondary_axis is false", () => {
    const option = buildChartOption({ ...combo, stack: true, secondary_axis: false }, rows, "dark");
    const series = seriesOf(option);
    expect(series.slice(0, 2).every((entry) => entry.stack === "bars")).toBe(true);
    expect(series[2].stack).toBeUndefined();
    expect(series.map((entry) => entry.yAxisIndex)).toEqual([0, 0, 0]);
    expect(Array.isArray(axis(option, "yAxis"))).toBe(false);
  });

  it("tooltip names the x value and formats each series by its column", () => {
    const chart: ComboChart = { ...combo, x: { column: "region" } };
    const option = buildChartOption(chart, rows, "light");
    const formatter = ((option as AnyRecord).tooltip as { formatter: (p: unknown) => string }).formatter;
    const series = seriesOf(option);
    const bar = (series[0].data as AnyRecord[])[0];
    const line = (series[2].data as AnyRecord[])[0];
    expect(formatter([{ seriesName: "Revenue", data: bar }, { seriesName: "Customers", data: line }])).toBe(
      "North<br/>Revenue: $15.00<br/>Customers: 110",
    );
  });
});

describe("buildChartOption heatmap", () => {
  const heatmap: HeatmapChart = {
    ...base,
    type: "heatmap",
    x: { column: "month", type: "date", label: "Month" },
    y: { column: "region" },
    value: { column: "revenue", format: "integer" },
  };

  it("builds cells on category axes with a continuous visualMap over the data range", () => {
    const option = buildChartOption(heatmap, rows, "light") as AnyRecord;
    const series = seriesOf(option);
    expect(series).toHaveLength(1);
    expect(series[0].type).toBe("heatmap");
    expect((series[0].data as { value: unknown }[]).map((cell) => cell.value)).toEqual([
      [0, 0, 10],
      [0, 1, 20],
      [1, 0, 15],
      [1, 1, 25],
    ]);
    expect(option.xAxis).toMatchObject({ type: "category", data: ["Jan 2024", "Feb 2024"] });
    expect(option.yAxis).toMatchObject({ type: "category", data: ["North", "South"] });
    expect(option.visualMap).toMatchObject({
      type: "continuous",
      min: 10,
      max: 25,
      inRange: { color: heatmapRange(LIGHT_THEME) },
    });
    expect((series[0].label as { show: boolean }).show).toBe(true);
    const formatter = (option.tooltip as { formatter: (p: unknown) => string }).formatter;
    expect(formatter({ data: (series[0].data as unknown[])[3] })).toBe(
      "Month: Feb 2024<br/>region: South<br/>revenue: 25",
    );
  });

  it("hides labels over 100 cells unless show_values is set", () => {
    const many: DatasetRows = [];
    for (let x = 0; x < 11; x += 1) {
      for (let y = 0; y < 10; y += 1) many.push({ x: "x" + x, y: "y" + y, v: x * y });
    }
    const chart: HeatmapChart = { ...base, type: "heatmap", x: { column: "x" }, y: { column: "y" }, value: { column: "v" } };
    expect((seriesOf(buildChartOption(chart, many, "light"))[0].label as { show: boolean }).show).toBe(false);
    expect((seriesOf(buildChartOption({ ...chart, show_values: true }, many, "light"))[0].label as { show: boolean }).show).toBe(true);
    const option = buildChartOption(chart, [], "light") as AnyRecord;
    expect(option.visualMap).toMatchObject({ min: 0, max: 1 });
  });

  it("mixes hex colors", () => {
    expect(mixHex("#000000", "#ffffff", 0.5)).toBe("#808080");
    expect(mixHex("#102030", "#102030", 0.3)).toBe("#102030");
    expect(heatmapRange(LIGHT_THEME)[1]).toBe(LIGHT_THEME.palette[0]);
  });
});
