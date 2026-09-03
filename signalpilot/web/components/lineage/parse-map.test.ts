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
