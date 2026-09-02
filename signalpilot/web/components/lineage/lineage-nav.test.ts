import { describe, expect, it } from "vitest";

import { lineageCone, parseMap, type RawMapGraph } from "./parse-map";
import {
  canonicalRef,
  lineagePath,
  pathBetween,
  rawSourcesFor,
  resolveModelRef,
  stageColumns,
  suggestNames,
} from "./lineage-nav";

/**
 * Fixture DAG (p = main package, p2 = an installed package with a name clash):
 *
 *   source.p.raw.orders ──> stg_orders ──┬──> int_orders ──> rpt_funnel
 *                                        └──────────────────────^   ^
 *   source.p.raw.customers > stg_customers ──> int_orders           |
 *   legacy_dump (model, no parents — undeclared root) ──────────────┘
 *
 *   model.p2.stg_orders — package model with the same name as p's stg_orders.
 */
const S_ORDERS = "source.p.raw.orders";
const S_CUSTOMERS = "source.p.raw.customers";
const STG_ORDERS = "model.p.stg_orders";
const STG_CUSTOMERS = "model.p.stg_customers";
const INT_ORDERS = "model.p.int_orders";
const RPT_FUNNEL = "model.p.rpt_funnel";
const LEGACY = "model.p.legacy_dump";
const PKG_STG_ORDERS = "model.p2.stg_orders";

function node(name: string, extra: Record<string, unknown> = {}) {
  return { name, resource_type: "model", schema: "analytics", database: "dw", ...extra };
}

const raw: RawMapGraph = {
  metadata: { project_name: "p", dbt_version: "1.8.0" },
  nodes: {
    [STG_ORDERS]: node("stg_orders"),
    [STG_CUSTOMERS]: node("stg_customers"),
    [INT_ORDERS]: node("int_orders"),
    [RPT_FUNNEL]: node("rpt_funnel"),
    [LEGACY]: node("legacy_dump", { schema: "scratch" }),
    [PKG_STG_ORDERS]: node("stg_orders", { schema: "pkg" }),
  },
  sources: {
    [S_ORDERS]: { name: "orders", resource_type: "source", schema: "raw", database: "dw" },
    [S_CUSTOMERS]: { name: "customers", resource_type: "source", schema: "raw", database: "dw" },
  },
  parent_map: {
    [STG_ORDERS]: [S_ORDERS],
    [STG_CUSTOMERS]: [S_CUSTOMERS],
    [INT_ORDERS]: [STG_ORDERS, STG_CUSTOMERS],
    [RPT_FUNNEL]: [INT_ORDERS, STG_ORDERS, LEGACY],
    [LEGACY]: [],
    [PKG_STG_ORDERS]: [],
    [S_ORDERS]: [],
    [S_CUSTOMERS]: [],
  },
  child_map: {
    [S_ORDERS]: [STG_ORDERS],
    [S_CUSTOMERS]: [STG_CUSTOMERS],
    [STG_ORDERS]: [INT_ORDERS, RPT_FUNNEL],
    [STG_CUSTOMERS]: [INT_ORDERS],
    [INT_ORDERS]: [RPT_FUNNEL],
    [LEGACY]: [RPT_FUNNEL],
    [RPT_FUNNEL]: [],
    [PKG_STG_ORDERS]: [],
  },
};

const parsed = parseMap(raw);

describe("resolveModelRef", () => {
  it("resolves an exact unique_id", () => {
    expect(resolveModelRef(parsed, RPT_FUNNEL)).toEqual({ kind: "found", id: RPT_FUNNEL });
  });

  it("resolves a bare model name (the canonical share form)", () => {
    expect(resolveModelRef(parsed, "rpt_funnel")).toEqual({ kind: "found", id: RPT_FUNNEL });
  });

  it("matches names case-insensitively", () => {
    expect(resolveModelRef(parsed, "RPT_Funnel")).toEqual({ kind: "found", id: RPT_FUNNEL });
  });

  it("resolves a source by name", () => {
    expect(resolveModelRef(parsed, "orders")).toEqual({ kind: "found", id: S_ORDERS });
  });

  it("returns all candidates when a name is ambiguous across packages", () => {
    const res = resolveModelRef(parsed, "stg_orders");
    expect(res.kind).toBe("ambiguous");
    if (res.kind === "ambiguous") {
      expect(res.ids.sort()).toEqual([STG_ORDERS, PKG_STG_ORDERS].sort());
    }
  });

  it("a full unique_id beats name ambiguity", () => {
    expect(resolveModelRef(parsed, PKG_STG_ORDERS)).toEqual({ kind: "found", id: PKG_STG_ORDERS });
  });

  it("falls back to the last segment of a stale unique_id", () => {
    expect(resolveModelRef(parsed, "model.renamed_project.rpt_funnel")).toEqual({
      kind: "found",
      id: RPT_FUNNEL,
    });
  });

  it("offers fuzzy suggestions for a typo", () => {
    const res = resolveModelRef(parsed, "rpt_funnnel");
    expect(res.kind).toBe("not-found");
    if (res.kind === "not-found") {
      expect(res.suggestions[0]).toBe("rpt_funnel");
      expect(res.suggestions.length).toBeLessThanOrEqual(3);
    }
  });

  it("suggests nothing for garbage", () => {
    const res = resolveModelRef(parsed, "zzzzqqqqxxxx");
    expect(res.kind).toBe("not-found");
    if (res.kind === "not-found") expect(res.suggestions).toEqual([]);
  });
});

describe("canonicalRef / lineagePath", () => {
  it("uses the bare name when unique", () => {
    expect(canonicalRef(parsed, RPT_FUNNEL)).toBe("rpt_funnel");
  });

  it("falls back to the unique_id when the name is ambiguous", () => {
    expect(canonicalRef(parsed, STG_ORDERS)).toBe(STG_ORDERS);
  });

  it("builds encoded paths with an optional /raw qualifier", () => {
    expect(lineagePath("rpt_funnel")).toBe("/lineage/rpt_funnel");
    expect(lineagePath("rpt_funnel", true)).toBe("/lineage/rpt_funnel/raw");
    expect(lineagePath(STG_ORDERS)).toBe(`/lineage/${encodeURIComponent(STG_ORDERS)}`);
  });
});

describe("suggestNames", () => {
  it("prefers prefix and substring matches", () => {
    expect(suggestNames(parsed, "stg")[0].startsWith("stg_")).toBe(true);
    expect(suggestNames(parsed, "funnel")).toContain("rpt_funnel");
  });
});

describe("rawSourcesFor", () => {
  it("deduplicates sources and counts distinct paths", () => {
    const { rows } = rawSourcesFor(parsed, RPT_FUNNEL);
    const orders = rows.find((r) => r.id === S_ORDERS);
    const customers = rows.find((r) => r.id === S_CUSTOMERS);
    expect(orders).toBeDefined();
    // orders -> stg_orders -> rpt AND orders -> stg_orders -> int -> rpt
    expect(orders!.pathCount).toBe(2);
    expect(orders!.declared).toBe(true);
    expect(orders!.relation).toBe("dw.raw.orders");
    expect(customers!.pathCount).toBe(1);
  });

  it("tags non-source lineage roots as undeclared", () => {
    const { rows } = rawSourcesFor(parsed, RPT_FUNNEL);
    const legacy = rows.find((r) => r.id === LEGACY);
    expect(legacy).toBeDefined();
    expect(legacy!.declared).toBe(false);
  });

  it("returns no rows for a root model and lists what a mart-on-mart builds on", () => {
    const { rows, buildsOn } = rawSourcesFor(parsed, LEGACY);
    expect(rows).toEqual([]);
    expect(buildsOn).toEqual([]);
    const funnel = rawSourcesFor(parsed, RPT_FUNNEL);
    expect(funnel.buildsOn.map((m) => m.id).sort()).toEqual(
      [INT_ORDERS, STG_ORDERS, LEGACY].sort(),
    );
  });
});

describe("stageColumns", () => {
  it("assigns cone members to labeled stages in pipeline order", () => {
    const cone = lineageCone(parsed, RPT_FUNNEL);
    const { stages, columnOf } = stageColumns(parsed, cone);
    expect(stages.map((s) => s.label)).toEqual(["Sources", "Staging", "Intermediate", "Marts"]);
    expect(stages[0].ids.sort()).toEqual([S_CUSTOMERS, S_ORDERS].sort());
    expect(columnOf.get(RPT_FUNNEL)).toBe(3);
    // `other` root gets a graph-depth column (stage 1 -> "Staging" column).
    expect(columnOf.get(LEGACY)).toBe(1);
  });
});

describe("pathBetween", () => {
  it("collects every node on any source->focus path", () => {
    const path = pathBetween(parsed, S_ORDERS, RPT_FUNNEL);
    expect(path.has(STG_ORDERS)).toBe(true);
    expect(path.has(INT_ORDERS)).toBe(true);
    expect(path.has(S_ORDERS)).toBe(true);
    expect(path.has(RPT_FUNNEL)).toBe(true);
    expect(path.has(S_CUSTOMERS)).toBe(false);
    expect(path.has(STG_CUSTOMERS)).toBe(false);
    expect(path.has(LEGACY)).toBe(false);
  });
});
