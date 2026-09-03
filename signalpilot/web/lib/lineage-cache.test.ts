import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getDbtMap, getDbtMapColumns, getDbtMapCone, getDbtMapModelSql } from "~/lib/api";
import { LineageCache } from "./lineage-cache";

// Fixture: a three-model chain with a source, in the gateway's three shapes.
const SRC = "source.demo.shop.refunds";
const STG = "model.demo.stg_refunds";
const FCT = "model.demo.fct_orders";
const MART = "model.demo.mart_orders_daily";

const info = (updated_at = 100, revision = 3) => ({
  id: "map-1",
  project_id: "p1",
  branch: "main",
  revision,
  status: "success",
  trigger: "manual",
  error: null,
  dbt_version: "1.9.0",
  node_count: 4,
  manifest_bytes: 10,
  created_at: 1,
  updated_at,
});

const skelNode = (name: string, path: string, column_count: number) => ({
  name,
  resource_type: "model",
  path,
  schema: "analytics",
  database: "demo",
  config: { materialized: "table" },
  column_count,
  tests: [{ name: `unique_${name}_id`, test_metadata: { name: "unique", kwargs: { column_name: "id" } } }],
});

const parentMap = { [SRC]: [], [STG]: [SRC], [FCT]: [STG], [MART]: [FCT] };
const childMap = { [SRC]: [STG], [STG]: [FCT], [FCT]: [MART], [MART]: [] };

function skeletonBody(updated_at = 100) {
  return {
    status: "success",
    map: info(updated_at),
    graph: {
      metadata: { project_name: "demo", variant: "skeleton" },
      nodes: {
        [STG]: skelNode("stg_refunds", "staging/stg_refunds.sql", 3),
        [FCT]: skelNode("fct_orders", "facts/fct_orders.sql", 5),
        [MART]: skelNode("mart_orders_daily", "marts/mart_orders_daily.sql", 2),
      },
      sources: { [SRC]: { name: "refunds", resource_type: "source", schema: "shop", column_count: 1 } },
      parent_map: parentMap,
      child_map: childMap,
    },
  };
}

function fullBody() {
  const b = skeletonBody();
  const withCols = (n: Record<string, unknown>) => ({
    ...n,
    column_count: undefined,
    tests: undefined,
    columns: { id: { name: "id", data_type: "int" } },
  });
  return {
    ...b,
    graph: {
      ...b.graph,
      metadata: { project_name: "demo" },
      nodes: Object.fromEntries(Object.entries(b.graph.nodes).map(([k, v]) => [k, withCols(v)])),
    },
  };
}

function coneBody(updated_at = 100) {
  const g = skeletonBody(updated_at).graph;
  return {
    status: "success",
    map: info(updated_at),
    model: {
      unique_id: FCT,
      ...g.nodes[FCT],
      columns: [
        { name: "order_id", data_type: "int" },
        { name: "refund_amount", description: "net of fees", data_type: "numeric" },
      ],
    },
    graph: {
      metadata: { project_name: "demo", variant: "cone" },
      nodes: { [STG]: g.nodes[STG], [FCT]: g.nodes[FCT], [MART]: g.nodes[MART] },
      sources: g.sources,
      parent_map: parentMap,
      child_map: childMap,
    },
    cone: { upstream: [STG, SRC], downstream: [MART] },
  };
}

type Reply = { status: number; body: unknown };
const calls: string[] = [];
let replies: (url: string) => Reply;

function installFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.endsWith("/api/local-key")) {
        return { ok: false, status: 404, json: async (): Promise<unknown> => null };
      }
      calls.push(url.replace("http://localhost:3300", ""));
      const r = replies(url);
      return {
        ok: r.status < 400,
        status: r.status,
        text: async () => JSON.stringify(r.body),
        json: async () => r.body,
      };
    }),
  );
}

const api = { getDbtMap, getDbtMapCone, getDbtMapColumns, getDbtMapModelSql };

/** Default gateway: every new endpoint present. */
function sqlBody(unique_id: string) {
  return {
    unique_id,
    name: unique_id.split(".").pop(),
    path: "facts/fct_orders.sql",
    original_file_path: "models/facts/fct_orders.sql",
    language: "sql",
    raw_sql: "select * from {{ ref('stg_refunds') }}",
    compiled_sql: "select * from demo.analytics.stg_refunds",
    source: "manifest",
  };
}

function modernGateway(url: string): Reply {
  if (/\/dbt-map\/model\/[^/?]+\/sql/.test(url)) {
    if (url.includes("source.")) return { status: 404, body: { detail: "no sql" } };
    const id = decodeURIComponent(/model\/([^/?]+)\/sql/.exec(url)![1]);
    return { status: 200, body: sqlBody(id) };
  }
  if (url.includes("/dbt-map/model/")) return { status: 200, body: coneBody() };
  if (url.includes("/dbt-map/columns")) {
    const ids = new URL(url).searchParams.get("nodes")!.split(",");
    return {
      status: 200,
      body: { columns: Object.fromEntries(ids.map((id) => [id, [{ name: `${id.split(".").pop()}_id` }]])) },
    };
  }
  if (url.includes("graph=skeleton")) return { status: 200, body: skeletonBody() };
  return { status: 200, body: fullBody() };
}

describe("LineageCache", () => {
  let cache: LineageCache;

  beforeEach(() => {
    calls.length = 0;
    replies = modernGateway;
    installFetch();
    cache = new LineageCache(api);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("dedupes in-flight skeleton requests per (project, branch)", async () => {
    const [a, b] = await Promise.all([cache.loadSkeleton("p1"), cache.loadSkeleton("p1")]);
    expect(a).toBe(b);
    expect(calls).toEqual(["/api/workspace-projects/p1/dbt-map?graph=skeleton"]);
    await cache.loadSkeleton("p1", "dev");
    expect(calls).toHaveLength(2);
    expect(calls[1]).toContain("branch=dev");
    // A settled load is served from memory.
    await cache.loadSkeleton("p1");
    expect(calls).toHaveLength(2);
    expect(cache.peekSkeleton("p1")).toBe(a);
  });

  it("parses skeleton nodes with column counts and inline tests", async () => {
    const s = await cache.loadSkeleton("p1");
    expect(s.parsed?.variant).toBe("skeleton");
    const fct = s.parsed!.models.get(FCT)!;
    expect(fct.columnsLoaded).toBe(false);
    expect(fct.columnCount).toBe(5);
    expect(fct.columns).toEqual([]);
    expect(fct.tests).toEqual([{ name: "unique_fct_orders_id", type: "unique", column: "id" }]);
    expect(fct.parents).toEqual([STG]);
    expect(s.parsed!.edges).toHaveLength(3);
  });

  it("merges the cone's focused columns into the skeleton's column cache", async () => {
    const cone = await cache.loadCone("p1", "fct_orders");
    expect(cone?.focusId).toBe(FCT);
    expect(cone?.parsed?.variant).toBe("cone");
    expect(cone?.parsed?.models.get(FCT)?.columnsLoaded).toBe(true);
    expect(cone?.parsed?.models.get(FCT)?.columns.map((c) => c.name)).toEqual([
      "order_id",
      "refund_amount",
    ]);
    expect(cone?.parsed?.models.size).toBe(4);

    const skel = await cache.loadSkeleton("p1");
    expect(skel.parsed?.models.get(FCT)?.columnsLoaded).toBe(false);
    // The focused model's columns are already there; no request needed.
    expect(cache.peekColumns("p1", FCT)?.map((c) => c.name)).toEqual(["order_id", "refund_amount"]);
    const before = calls.length;
    const got = await cache.loadColumns("p1", [FCT]);
    expect(got[FCT]).toHaveLength(2);
    expect(calls).toHaveLength(before);
  });

  it("batches column requests and only asks for missing ids", async () => {
    await cache.loadCone("p1", "fct_orders");
    const [a, b] = await Promise.all([
      cache.loadColumns("p1", [FCT, STG, MART]),
      cache.loadColumns("p1", [STG]),
    ]);
    const columnCalls = calls.filter((c) => c.includes("/dbt-map/columns"));
    expect(columnCalls).toHaveLength(1);
    const ids = new URL(`http://x${columnCalls[0]}`).searchParams.get("nodes")!.split(",");
    expect(ids.sort()).toEqual([MART, STG].sort());
    expect(a[STG]).toEqual([{ name: "stg_refunds_id", description: "", dataType: undefined }]);
    expect(b[STG]).toBe(a[STG]);
    expect(cache.peekColumns("p1", MART)).toHaveLength(1);
  });

  it("invalidates on a new updated_at and keeps the entry otherwise", async () => {
    await cache.loadSkeleton("p1");
    await cache.loadCone("p1", "fct_orders");
    expect(cache.invalidate("p1", null, 100)).toBe(false);
    expect(cache.peekSkeleton("p1")).not.toBeNull();
    expect(cache.invalidate("p1", null, 200)).toBe(true);
    expect(cache.peekSkeleton("p1")).toBeNull();
    expect(cache.peekCone("p1", "fct_orders")).toBeNull();
    expect(cache.peekColumns("p1", FCT)).toBeNull();
    const before = calls.length;
    await cache.loadSkeleton("p1");
    expect(calls.length).toBe(before + 1);
  });

  it("drops cones and columns when a response reports another revision", async () => {
    await cache.loadCone("p1", "fct_orders");
    expect(cache.revision("p1")).toBe("3:100");
    replies = (url) =>
      url.includes("graph=skeleton") ? { status: 200, body: skeletonBody(250) } : modernGateway(url);
    await cache.loadSkeleton("p1");
    expect(cache.revision("p1")).toBe("3:250");
    expect(cache.peekCone("p1", "fct_orders")).toBeNull();
    expect(cache.peekColumns("p1", FCT)).toBeNull();
    expect(cache.peekSkeleton("p1")).not.toBeNull();
  });

  it("falls back cone -> skeleton -> full graph on an older gateway", async () => {
    replies = (url) => {
      if (url.includes("/dbt-map/model/")) return { status: 404, body: { detail: "Not Found" } };
      if (url.includes("graph=skeleton")) return { status: 422, body: { detail: "unknown param" } };
      return { status: 200, body: fullBody() };
    };
    const [cone, skel] = await Promise.all([
      cache.loadCone("p1", "fct_orders"),
      cache.loadSkeleton("p1"),
    ]);
    expect(cone).toBeNull();
    expect(skel.parsed?.variant).toBe("full");
    expect(skel.parsed?.models.get(FCT)?.columnsLoaded).toBe(true);
    expect(skel.parsed?.models.get(FCT)?.columnCount).toBe(1);
    expect(calls).toEqual([
      "/api/workspace-projects/p1/dbt-map/model/fct_orders?hops=all",
      "/api/workspace-projects/p1/dbt-map?graph=skeleton",
      "/api/workspace-projects/p1/dbt-map",
    ]);
    // Full-graph columns are primed; the columns endpoint is never called.
    expect(cache.peekColumns("p1", FCT)).toHaveLength(1);
    await cache.loadColumns("p1", [FCT, STG]);
    expect(calls).toHaveLength(3);
    // The failed cone is remembered for this ref; the skeleton is the answer.
    expect(cache.peekCone("p1", "fct_orders")).toBeNull();
    await cache.loadCone("p1", "fct_orders");
    expect(calls).toHaveLength(3);
  });

  it("dedupes SQL per unique_id and remembers nodes without SQL", async () => {
    const [a, b] = await Promise.all([cache.loadSql("p1", FCT), cache.loadSql("p1", FCT)]);
    expect(a).toBe(b);
    expect(a?.raw_sql).toContain("stg_refunds");
    expect(a?.compiled_sql).toContain("demo.analytics");
    expect(calls).toEqual([`/api/workspace-projects/p1/dbt-map/model/${encodeURIComponent(FCT)}/sql`]);
    expect(cache.peekSql("p1", FCT)).toBe(a);
    expect(cache.peekSql("p1", STG)).toBeUndefined();
    // A source answers 404: cached as null, asked once.
    expect(await cache.loadSql("p1", SRC)).toBeNull();
    expect(await cache.loadSql("p1", SRC)).toBeNull();
    expect(cache.peekSql("p1", SRC)).toBeNull();
    expect(calls).toHaveLength(2);
    // A new revision drops the SQL cache with the rest.
    await cache.loadSkeleton("p1");
    expect(cache.invalidate("p1", null, 999)).toBe(true);
    expect(cache.peekSql("p1", FCT)).toBeUndefined();
  });

  it("does not cache a failed SQL load", async () => {
    replies = () => ({ status: 500, body: { detail: "boom" } });
    await expect(cache.loadSql("p1", FCT)).rejects.toThrow(/500/);
    replies = modernGateway;
    expect((await cache.loadSql("p1", FCT))?.unique_id).toBe(FCT);
  });

  it("does not cache a failed skeleton load", async () => {
    replies = () => ({ status: 500, body: { detail: "boom" } });
    await expect(cache.loadSkeleton("p1")).rejects.toThrow(/500/);
    replies = modernGateway;
    const s = await cache.loadSkeleton("p1");
    expect(s.parsed).not.toBeNull();
  });

  it("carries a not-compiled status through without a graph", async () => {
    replies = () => ({ status: 200, body: { status: "running", map: info(), graph: null } });
    const s = await cache.loadSkeleton("p1");
    expect(s.status).toBe("running");
    expect(s.parsed).toBeNull();
    const c = await cache.loadCone("p1", "fct_orders");
    expect(c?.status).toBe("running");
    expect(c?.parsed).toBeNull();
  });
});
