import { describe, expect, it } from "vitest";

import type { DatasetRows } from "./datasets";
import { chartIsFailed, prepareChartRows, sortRows, unknownChartIssue } from "./prepare";
import type { DashboardChart, DashboardFilter, DashboardSpec } from "./schema";

const rows: DatasetRows = [
  { day: "2024-01-01", region: "North", revenue: 10, note: "a" },
  { day: "2024-01-02", region: "South", revenue: "20", note: null },
  { day: "2024-01-03", region: "East", revenue: 5, note: "c" },
  { day: "bad-date", region: "West", revenue: null, note: "d" },
];

function specWith(chart: Partial<DashboardChart> & Record<string, unknown>, filters: DashboardFilter[] = []): DashboardSpec {
  return {
    version: 1,
    title: "T",
    datasets: { sales: { rows } },
    filters,
    charts: [
      {
        id: "c1",
        type: "bar",
        title: "C",
        dataset: "sales",
        x: { column: "day", type: "category" },
        y: [{ column: "revenue" }],
        ...chart,
      } as DashboardChart,
    ],
  };
}

function run(spec: DashboardSpec, filterState?: Record<string, unknown>, datasets = { sales: rows }) {
  return prepareChartRows(spec.charts[0], spec, datasets, filterState);
}

const codes = (issues: { code: string }[]) => issues.map((issue) => issue.code);

describe("filters", () => {
  it("equals keeps matching rows and skips only null or undefined defaults", () => {
    const filter: DashboardFilter = { id: "f", label: "F", dataset: "sales", column: "region", type: "equals", default: "North" };
    expect(run(specWith({}, [filter])).rows).toHaveLength(1);
    expect(run(specWith({}, [{ ...filter, default: null }])).rows).toHaveLength(4);
    expect(run(specWith({}, [{ ...filter, default: undefined }])).rows).toHaveLength(4);
    expect(run(specWith({}, [filter]), { f: "South" }).rows[0].region).toBe("South");
  });

  it("equals treats an empty string as a value to match, like the Python side", () => {
    const filter: DashboardFilter = { id: "f", label: "F", dataset: "sales", column: "region", type: "equals", default: "" };
    const blank = [...rows, { day: "2024-01-05", region: "", revenue: 1, note: "n" }];
    expect(run(specWith({}, [filter]), undefined, { sales: blank }).rows.map((row) => row.day)).toEqual(["2024-01-05"]);
    expect(run(specWith({}, [{ ...filter, default: "North" }]), { f: "" }, { sales: blank }).rows).toHaveLength(1);
  });

  it("in keeps listed values and skips empty lists", () => {
    const filter: DashboardFilter = { id: "f", label: "F", dataset: "sales", column: "region", type: "in", default: ["North", "East"] };
    expect(run(specWith({}, [filter])).rows.map((row) => row.region)).toEqual(["North", "East"]);
    expect(run(specWith({}, [{ ...filter, default: [] }])).rows).toHaveLength(4);
  });

  it("date_range drops unparseable rows only when a bound is given", () => {
    const filter: DashboardFilter = { id: "f", label: "F", dataset: "sales", column: "day", type: "date_range", default: { from: "2024-01-02" } };
    expect(run(specWith({}, [filter])).rows.map((row) => row.day)).toEqual(["2024-01-02", "2024-01-03"]);
    expect(run(specWith({}, [{ ...filter, default: { to: "2024-01-01" } }])).rows).toHaveLength(1);
    expect(run(specWith({}, [{ ...filter, default: {} }])).rows).toHaveLength(4);
  });

  it("number_range drops non-numeric rows only when a bound is given", () => {
    const filter: DashboardFilter = { id: "f", label: "F", dataset: "sales", column: "revenue", type: "number_range", default: { min: 10, max: 20 } };
    expect(run(specWith({}, [filter])).rows.map((row) => row.region)).toEqual(["North", "South"]);
    expect(run(specWith({}, [{ ...filter, default: {} }])).rows).toHaveLength(4);
  });

  it("equals and in compare with String() semantics (null, booleans, integral numbers)", () => {
    const mixed: DatasetRows = [
      { k: null, v: 1 },
      { k: true, v: 2 },
      { k: 5, v: 3 },
      { k: "5", v: 4 },
      { k: 5.5, v: 5 },
    ];
    const spec = specWith({ x: { column: "k" }, y: [{ column: "v" }] });
    spec.datasets.sales = { rows: mixed };
    const withFilter = (filter: DashboardFilter) => {
      spec.filters = [filter];
      return prepareChartRows(spec.charts[0], spec, { sales: mixed }).rows.map((row) => row.v);
    };
    const equals = (value: unknown): DashboardFilter => ({ id: "f", label: "F", dataset: "sales", column: "k", type: "equals", default: value });
    expect(withFilter(equals("null"))).toEqual([1]);
    expect(withFilter(equals(true))).toEqual([2]);
    expect(withFilter(equals("true"))).toEqual([2]);
    expect(withFilter(equals(5))).toEqual([3, 4]);
    expect(withFilter(equals("5.0"))).toEqual([]);
    expect(withFilter(equals(5.5))).toEqual([5]);
    expect(withFilter({ ...equals(null), type: "in", default: [5, "true"] })).toEqual([2, 3, 4]);
  });

  it("ignores filters bound to other datasets", () => {
    const filter: DashboardFilter = { id: "f", label: "F", dataset: "other", column: "region", type: "equals", default: "North" };
    const spec = specWith({}, [filter]);
    spec.datasets.other = { rows: [{ region: "x" }] };
    expect(run(spec).rows).toHaveLength(4);
  });
});

describe("sort and limit", () => {
  it("sorts numerically with nulls last, stable, and honors direction", () => {
    const sorted = sortRows(rows, "revenue", "desc");
    expect(sorted.map((row) => row.region)).toEqual(["South", "North", "East", "West"]);
    expect(sortRows(rows, "revenue").map((row) => row.region)).toEqual(["East", "North", "South", "West"]);
    const stable = sortRows([{ k: 1, v: "a" }, { k: 1, v: "b" }, { k: 0, v: "c" }], "k");
    expect(stable.map((row) => row.v)).toEqual(["c", "a", "b"]);
  });

  it("sorts strings when either side is non-numeric", () => {
    expect(sortRows(rows, "region").map((row) => row.region)).toEqual(["East", "North", "South", "West"]);
  });

  it("applies sort then limit", () => {
    const result = run(specWith({ sort: { column: "revenue", direction: "desc" }, limit: 2 }));
    expect(result.rows.map((row) => row.region)).toEqual(["South", "North"]);
  });
});

describe("issues", () => {
  it("missing_dataset fails the chart", () => {
    const result = run(specWith({ dataset: "nope" }));
    expect(codes(result.issues)).toEqual(["missing_dataset"]);
    expect(result.issues[0].message).toContain('"c1"');
    expect(chartIsFailed(result.issues)).toBe(true);
  });

  it("snapshot_missing fails a SQL dataset whose rows were not loaded", () => {
    const spec = specWith({});
    spec.datasets.sales = { connection: "warehouse", sql: "select 1" };
    const result = prepareChartRows(spec.charts[0], spec, {});
    expect(codes(result.issues)).toEqual(["snapshot_missing"]);
    expect(result.issues[0].message).toBe(
      "Dataset 'sales' has no snapshot. Call sp.dashboard_dataset('sales', connection=..., sql=...) in the notebook.",
    );
    expect(chartIsFailed(result.issues)).toBe(true);
  });

  it("dataset_unreadable fails a static dataset whose rows were not passed", () => {
    const result = prepareChartRows(specWith({}).charts[0], specWith({}), {});
    expect(codes(result.issues)).toEqual(["dataset_unreadable"]);
    expect(result.issues[0].message).toContain('"sales"');
  });

  it("missing_column names the column and the available columns", () => {
    const result = run(specWith({ y: [{ column: "profit" }], sort: { column: "ghost" } }));
    expect(codes(result.issues)).toEqual(["missing_column", "missing_column"]);
    expect(result.issues[0].message).toContain('"profit"');
    expect(result.issues[0].message).toContain("day, region, revenue, note");
    expect(chartIsFailed(result.issues)).toBe(true);
    expect(result.rows).toEqual([]);
  });

  it("missing_column also covers filter columns bound to the dataset", () => {
    const filter: DashboardFilter = { id: "f", label: "F", dataset: "sales", column: "country", type: "equals" };
    expect(codes(run(specWith({}, [filter])).issues)).toEqual(["missing_column"]);
  });

  it("empty_dataset is a warning", () => {
    const filter: DashboardFilter = { id: "f", label: "F", dataset: "sales", column: "region", type: "equals", default: "Mars" };
    const result = run(specWith({}, [filter]));
    expect(codes(result.issues)).toEqual(["empty_dataset"]);
    expect(chartIsFailed(result.issues)).toBe(false);
  });

  it("non_numeric_y warns below the 90% threshold", () => {
    const result = run(specWith({ y: [{ column: "note" }] }));
    expect(codes(result.issues)).toEqual(["non_numeric_y"]);
    expect(result.issues[0].message).toContain('"note"');
    expect(run(specWith({})).issues).toEqual([]);
  });

  it("numeric and date ratios count empty-string cells as non-null failures", () => {
    // 3 numbers, 2 blanks: 60% numeric -> warn. Nulls are excluded as before.
    const mixed: DatasetRows = [
      { day: "2024-01-01", revenue: 1 },
      { day: "2024-01-02", revenue: "2" },
      { day: "2024-01-03", revenue: "+3" },
      { day: "", revenue: "" },
      { day: "", revenue: "" },
      { day: null, revenue: null },
    ];
    const spec = specWith({ x: { column: "day", type: "date" } });
    const result = prepareChartRows(spec.charts[0], spec, { sales: mixed });
    expect(codes(result.issues)).toEqual(["non_numeric_y", "unparseable_date"]);
    expect(result.issues[0].message).toContain("3 of 5");
  });

  it("unparseable_date warns for date axes", () => {
    const result = run(specWith({ x: { column: "day", type: "date" } }));
    expect(codes(result.issues)).toEqual(["unparseable_date"]);
    expect(result.issues[0].message).toContain('"day"');
  });

  it("too_many_rows caps at 50000", () => {
    const big: DatasetRows = Array.from({ length: 50_010 }, (_, index) => ({ day: "d", revenue: index }));
    const spec = specWith({});
    spec.datasets.sales = { rows: [] };
    const result = prepareChartRows(spec.charts[0], spec, { sales: big });
    expect(codes(result.issues)).toEqual(["too_many_rows"]);
    expect(result.rows).toHaveLength(50_000);
  });

  it("series_with_multi_y fails the chart", () => {
    const result = run(specWith({ y: [{ column: "revenue" }, { column: "revenue" }], series: { column: "region" } }));
    expect(codes(result.issues)).toEqual(["series_with_multi_y"]);
    expect(chartIsFailed(result.issues)).toBe(true);
  });

  it("kpi, pie and scatter columns are checked", () => {
    const kpi = run(specWith({ type: "kpi", value: { column: "note" }, x: undefined, y: undefined }));
    expect(codes(kpi.issues)).toEqual(["non_numeric_y"]);
    const scatter = run(specWith({ type: "scatter", x: { column: "day" }, y: { column: "revenue" }, size: "nope" }));
    expect(codes(scatter.issues)).toEqual(["missing_column"]);
    const pie = run(specWith({ type: "pie", label: "region", value: { column: "revenue" }, x: undefined, y: undefined }));
    expect(pie.issues).toEqual([]);
  });

  it("unknown_chart lists valid ids", () => {
    const issue = unknownChartIssue("zzz", specWith({}));
    expect(issue.code).toBe("unknown_chart");
    expect(issue.message).toContain("c1");
  });
});

describe("filters without a dataset bind by column", () => {
  const spec = {
    version: 1 as const,
    title: "T",
    datasets: {
      a: { rows: [{ region: "N", v: 1 }, { region: "S", v: 2 }] },
      b: { rows: [{ region: "N", w: 10 }, { region: "S", w: 20 }] },
      c: { rows: [{ other: "x", z: 5 }] },
    },
    filters: [{ id: "region", label: "Region", column: "region", type: "in" as const, default: ["N"] }],
    charts: [
      { id: "ca", type: "kpi" as const, title: "A", dataset: "a", value: { column: "v" } },
      { id: "cb", type: "kpi" as const, title: "B", dataset: "b", value: { column: "w" } },
      { id: "cc", type: "kpi" as const, title: "C", dataset: "c", value: { column: "z" } },
    ],
  };
  const datasets = { a: spec.datasets.a.rows, b: spec.datasets.b.rows, c: spec.datasets.c.rows };

  it("applies to every dataset that has the column", () => {
    expect(prepareChartRows(spec.charts[0], spec, datasets).rows).toEqual([{ region: "N", v: 1 }]);
    expect(prepareChartRows(spec.charts[1], spec, datasets).rows).toEqual([{ region: "N", w: 10 }]);
  });

  it("leaves datasets without the column alone and reports no missing column", () => {
    const result = prepareChartRows(spec.charts[2], spec, datasets);
    expect(result.rows).toEqual([{ other: "x", z: 5 }]);
    expect(result.issues).toEqual([]);
  });

  it("a bound filter still requires its column on that dataset", () => {
    const bound = { ...spec, filters: [{ ...spec.filters[0], dataset: "c" }] };
    const result = prepareChartRows(bound.charts[2], bound, datasets);
    expect(result.issues.map((issue) => issue.code)).toContain("missing_column");
  });

  it("live filter state drives every bound dataset", () => {
    expect(prepareChartRows(spec.charts[1], spec, datasets, { region: ["S"] }).rows).toEqual([{ region: "S", w: 20 }]);
  });
});

