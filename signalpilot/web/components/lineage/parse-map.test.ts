import { describe, expect, it } from "vitest";

import { lineageCone, parseColumns, parseMap, type RawMapGraph } from "./parse-map";

const SRC = "source.demo.shop.orders";
const STG = "model.demo.stg_orders";
const FCT = "model.demo.fct_orders";
const TEST = "test.demo.unique_fct_orders_id";

const full: RawMapGraph = {
  metadata: { project_name: "demo", dbt_version: "1.9.0" },
  nodes: {
    [STG]: {
      name: "stg_orders",
      resource_type: "model",
      path: "staging/stg_orders.sql",
      columns: { id: { name: "id", data_type: "int" }, amount: { name: "amount" } },
    },
    [FCT]: {
      name: "fct_orders",
      resource_type: "model",
      path: "facts/fct_orders.sql",
      columns: { id: { name: "id", description: "pk" } },
    },
    [TEST]: {
      name: "unique_fct_orders_id",
      resource_type: "test",
      test_metadata: { name: "unique", kwargs: { column_name: "id" } },
    },
  },
  sources: { [SRC]: { name: "orders", resource_type: "source", columns: {} } },
  parent_map: { [SRC]: [], [STG]: [SRC], [FCT]: [STG], [TEST]: [FCT] },
  child_map: { [SRC]: [STG], [STG]: [FCT], [FCT]: [TEST], [TEST]: [] },
};

const skeleton: RawMapGraph = {
  metadata: { project_name: "demo", dbt_version: "1.9.0", variant: "skeleton" },
  nodes: {
    [STG]: { name: "stg_orders", resource_type: "model", path: "staging/stg_orders.sql", column_count: 2, tests: [] },
    [FCT]: {
      name: "fct_orders",
      resource_type: "model",
      path: "facts/fct_orders.sql",
      column_count: 1,
      tests: [{ name: "unique_fct_orders_id", test_metadata: { name: "unique", kwargs: { column_name: "id" } } }],
    },
  },
  sources: { [SRC]: { name: "orders", resource_type: "source", column_count: 0 } },
  parent_map: { [SRC]: [], [STG]: [SRC], [FCT]: [STG] },
  child_map: { [SRC]: [STG], [STG]: [FCT], [FCT]: [] },
};

describe("parseMap", () => {
  it("parses the full graph with inline columns and test nodes", () => {
    const p = parseMap(full);
    expect(p.variant).toBe("full");
    expect([...p.models.keys()].sort()).toEqual([FCT, STG, SRC].sort());
    const fct = p.models.get(FCT)!;
    expect(fct.columnsLoaded).toBe(true);
    expect(fct.columnCount).toBe(1);
    expect(fct.columns).toEqual([{ name: "id", description: "pk", dataType: undefined }]);
    expect(fct.tests).toEqual([{ name: "unique_fct_orders_id", type: "unique", column: "id" }]);
    // Test nodes never become graph relations.
    expect(fct.children).toEqual([]);
    expect(p.edges.map((e) => e.id).sort()).toEqual([`${SRC}->${STG}`, `${STG}->${FCT}`].sort());
  });

  it("parses skeleton nodes: counts without columns, inline tests", () => {
    const p = parseMap(skeleton);
    expect(p.variant).toBe("skeleton");
    const stg = p.models.get(STG)!;
    expect(stg.columnsLoaded).toBe(false);
    expect(stg.columns).toEqual([]);
    expect(stg.columnCount).toBe(2);
    expect(stg.tests).toEqual([]);
    const fct = p.models.get(FCT)!;
    expect(fct.tests).toEqual([{ name: "unique_fct_orders_id", type: "unique", column: "id" }]);
    expect(p.models.get(SRC)!.layer).toBe("source");
    expect(p.layerCounts.staging).toBe(1);
    expect(p.layerCounts.fact).toBe(1);
  });

  it("classifies core, prep and report models, then unmatched ones by position", () => {
    const model = (name: string, path: string) => ({ name, resource_type: "model", path });
    const p = parseMap({
      metadata: { project_name: "demo" },
      nodes: {
        "model.d.core_cost_line": model("core_cost_line", "models/core/core_cost_line.sql"),
        "model.d.pool": model("pool", "models/core/pool.sql"),
        "model.d.fct_sales_lines": model("fct_sales_lines", "models/core/fct_sales_lines.sql"),
        "model.d.prep_rows": model("prep_rows", "models/misc/prep_rows.sql"),
        "model.d.report_weekly": model("report_weekly", "models/misc/report_weekly.sql"),
        "model.d.scratch_join": model("scratch_join", "models/adhoc/scratch_join.sql"),
        "model.d.quick_check": model("quick_check", "models/adhoc/quick_check.sql"),
        "model.d.lonely": model("lonely", "models/adhoc/lonely.sql"),
      },
      parent_map: {
        "model.d.scratch_join": [],
        "model.d.quick_check": ["model.d.scratch_join"],
        "model.d.lonely": [],
      },
      child_map: {
        "model.d.scratch_join": ["model.d.quick_check"],
        "model.d.quick_check": [],
        "model.d.lonely": [],
      },
    });
    const layer = (id: string) => p.models.get(id)!.layer;
    expect(layer("model.d.core_cost_line")).toBe("intermediate");
    expect(layer("model.d.pool")).toBe("intermediate"); // core/ folder
    // A name prefix outranks the folder it sits in.
    expect(layer("model.d.fct_sales_lines")).toBe("fact");
    expect(layer("model.d.prep_rows")).toBe("intermediate");
    expect(layer("model.d.report_weekly")).toBe("mart");
    // No rule matches: a model that feeds others is intermediate, an
    // endpoint is a mart, and only a model with no neighbours stays other.
    expect(layer("model.d.scratch_join")).toBe("intermediate");
    expect(layer("model.d.quick_check")).toBe("mart");
    expect(layer("model.d.lonely")).toBe("other");
    expect(p.layerCounts.other).toBe(1);
  });

  it("keys layers on declarations and the compiled schema before names", () => {
    const node = (name: string, extra: Record<string, unknown>) => ({
      name, resource_type: "model", path: `misc/${name}.sql`, ...extra,
    });
    const p = parseMap({
      metadata: { project_name: "demo" },
      nodes: {
        "model.d.declared": node("stg_declared", { schema: "staging", layer: "mart" }),
        "model.d.tagged": node("anything", { schema: "main", tags: ["daily", "Intermediate"] }),
        "model.d.core_tag": node("orders_rollup", { schema: "marts", tags: ["core"] }),
        "model.d.prefixed_schema": node("orders_clean", { schema: "dbt_prod_staging" }),
        "model.d.schema_over_name": node("stg_legacy_summary", { schema: "marts" }),
        "model.d.dim_in_marts": node("dim_customer", { schema: "marts" }),
        "model.d.fct_in_core": node("fct_sales_lines", { schema: "core" }),
        "model.d.core_schema": node("pool", { schema: "core" }),
        "model.d.default_schema": node("stg_orders", { schema: "dbo" }),
      },
    });
    const layer = (id: string) => p.models.get(id)!.layer;
    expect(layer("model.d.declared")).toBe("mart"); // meta.layer wins
    expect(layer("model.d.tagged")).toBe("intermediate");
    expect(layer("model.d.core_tag")).toBe("mart"); // a "core" tag is not a layer
    expect(layer("model.d.prefixed_schema")).toBe("staging");
    expect(layer("model.d.schema_over_name")).toBe("mart");
    expect(layer("model.d.dim_in_marts")).toBe("dimension");
    expect(layer("model.d.fct_in_core")).toBe("fact");
    expect(layer("model.d.core_schema")).toBe("intermediate");
    // A default schema says nothing; the name prefix decides.
    expect(layer("model.d.default_schema")).toBe("staging");
  });

  it("keeps dbt sources in the map but out of the legend counts", () => {
    // The canvas never draws dbt sources; the Raw Tables panel still reads
    // them from the parsed map, so they stay in `models`.
    const p = parseMap(full);
    expect(p.models.has(SRC)).toBe(true);
    expect(p.layerCounts.source).toBe(0);
  });

  it("yields the same topology for skeleton and full graphs", () => {
    const a = parseMap(full);
    const b = parseMap(skeleton);
    expect([...b.models.keys()].sort()).toEqual([...a.models.keys()].sort());
    expect(b.edges.map((e) => e.id).sort()).toEqual(a.edges.map((e) => e.id).sort());
    expect([...lineageCone(b, STG)].sort()).toEqual([...lineageCone(a, STG)].sort());
    expect([...b.schemas.keys()]).toEqual([...a.schemas.keys()]);
  });

  it("accepts cone-shaped column arrays", () => {
    expect(parseColumns([{ name: "a", data_type: "int" }, { name: "b", description: "x" }])).toEqual([
      { name: "a", description: "", dataType: "int" },
      { name: "b", description: "x", dataType: undefined },
    ]);
    expect(parseColumns(undefined)).toEqual([]);
    const p = parseMap({
      ...skeleton,
      metadata: { variant: "cone" },
      nodes: { ...skeleton.nodes, [FCT]: { ...skeleton.nodes![FCT], columns: [{ name: "id" }] } },
    });
    expect(p.variant).toBe("cone");
    expect(p.models.get(FCT)!.columnsLoaded).toBe(true);
    expect(p.models.get(FCT)!.columnCount).toBe(1);
  });
});
