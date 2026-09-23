// @vitest-environment node
/**
 * Tooltips render with `renderMode: "html"`, so ECharts assigns the
 * formatter's string to innerHTML. Category values come from warehouse rows
 * and series labels from agent-authored dashboard JSON: every interpolated
 * string must be escaped, while normal values render exactly as before.
 */
import { describe, expect, it } from "vitest";

import type { DatasetRows } from "../datasets";
import { escapeHtml } from "../format";
import type { CartesianChart, ComboChart, HeatmapChart, PieChart, ScatterChart } from "../schema";
import { buildChartOption } from "./options";

const IMG = `<img src=x onerror=alert(1)>`;
const IMG_ESCAPED = "&lt;img src=x onerror=alert(1)&gt;";
const LABEL = `<b onmouseover=alert(2)>Revenue</b>`;
const LABEL_ESCAPED = "&lt;b onmouseover=alert(2)&gt;Revenue&lt;/b&gt;";

const rows: DatasetRows = [
  { region: IMG, month: "2024-01-01", revenue: 15, customers: 100, "<i>tag</i>": "a&b" },
  { region: "South", month: "2024-02-01", revenue: 25, customers: 200, "<i>tag</i>": "c" },
];

type AnyRecord = Record<string, unknown>;
const seriesOf = (option: unknown) => (option as { series: AnyRecord[] }).series;
const formatterOf = (option: unknown) =>
  ((option as AnyRecord).tooltip as { formatter: (p: unknown) => string }).formatter;
const base = { id: "c", title: "C", dataset: "d" };

describe("escapeHtml", () => {
  it("escapes markup-significant characters only", () => {
    expect(escapeHtml(IMG)).toBe(IMG_ESCAPED);
    expect(escapeHtml(`a & b "q" 'x'`)).toBe("a &amp; b &quot;q&quot; &#39;x&#39;");
    expect(escapeHtml("North")).toBe("North");
    expect(escapeHtml("$1,234.50 (12.3%)")).toBe("$1,234.50 (12.3%)");
  });
});

describe("tooltip formatters escape interpolated strings", () => {
  it("bar: category heading and series label", () => {
    const chart: CartesianChart = {
      ...base,
      type: "bar",
      x: { column: "region" },
      y: [{ column: "revenue", label: LABEL, format: "integer" }],
    };
    const option = buildChartOption(chart, rows, "light");
    const data = (seriesOf(option)[0].data as AnyRecord[])[0];
    const out = formatterOf(option)([{ seriesName: LABEL, data }]);
    expect(out).toBe(`${IMG_ESCAPED}<br/>${LABEL_ESCAPED}: 15`);
    expect(out).not.toContain("<img");
    expect(out).not.toContain("<b ");
  });

  it("bar: normal values are unchanged", () => {
    const chart: CartesianChart = {
      ...base,
      type: "bar",
      x: { column: "region" },
      y: [{ column: "revenue", label: "Revenue", format: "currency:USD" }],
    };
    const option = buildChartOption(chart, rows, "light");
    const data = (seriesOf(option)[0].data as AnyRecord[])[1];
    expect(formatterOf(option)([{ seriesName: "Revenue", data }])).toBe("South<br/>Revenue: $25.00");
  });

  it("pie: slice name", () => {
    const chart: PieChart = { ...base, type: "pie", label: "region", value: { column: "revenue" } };
    const option = buildChartOption(chart, rows, "light");
    const data = (seriesOf(option)[0].data as AnyRecord[])[0];
    const out = formatterOf(option)([{ name: IMG, data, percent: 37.5 }]);
    expect(out).toBe(`${IMG_ESCAPED}: 15 (37.5%)`);
  });

  it("scatter: labels, category x, size column and color group", () => {
    const chart: ScatterChart = {
      ...base,
      type: "scatter",
      x: { column: "region", label: LABEL },
      y: { column: "revenue", label: "<i>y</i>" },
      size: "<i>tag</i>",
      color: "region",
    };
    const option = buildChartOption(chart, rows, "light");
    const data = (seriesOf(option)[0].data as AnyRecord[])[0];
    const out = formatterOf(option)([{ data }]);
    expect(out).toBe(
      [
        IMG_ESCAPED,
        `${LABEL_ESCAPED}: ${IMG_ESCAPED}`,
        "&lt;i&gt;y&lt;/i&gt;: 15",
        "&lt;i&gt;tag&lt;/i&gt;: a&amp;b",
      ].join("<br/>"),
    );
  });

  it("combo: category heading and series names", () => {
    const chart: ComboChart = {
      ...base,
      type: "combo",
      x: { column: "region" },
      bars: [{ column: "revenue", label: LABEL }],
      lines: [{ column: "customers", label: "Customers" }],
    };
    const option = buildChartOption(chart, rows, "light");
    const series = seriesOf(option);
    const bar = (series[0].data as AnyRecord[])[0];
    const line = (series[1].data as AnyRecord[])[0];
    const out = formatterOf(option)([
      { seriesName: LABEL, data: bar },
      { seriesName: "Customers", data: line },
    ]);
    expect(out).toBe(`${IMG_ESCAPED}<br/>${LABEL_ESCAPED}: 15<br/>Customers: 100`);
  });

  it("heatmap: axis labels and category values", () => {
    const chart: HeatmapChart = {
      ...base,
      type: "heatmap",
      x: { column: "month", label: "<u>Month</u>" },
      y: { column: "region" },
      value: { column: "revenue", label: LABEL },
    };
    const option = buildChartOption(chart, rows, "light");
    const cell = (seriesOf(option)[0].data as unknown[])[0];
    const out = formatterOf(option)({ data: cell });
    expect(out).toBe(
      `&lt;u&gt;Month&lt;/u&gt;: 2024-01-01<br/>region: ${IMG_ESCAPED}<br/>${LABEL_ESCAPED}: 15`,
    );
  });
});
