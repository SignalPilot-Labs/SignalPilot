import type { BrowserContext, Route } from "@playwright/test";

/**
 * Mocked gateway for the lineage views: one project ("showcase-project")
 * with a four-node chain around stg_refunds, served in every shape the
 * client understands (skeleton, cone, columns, SQL, full, status poll).
 * `mockLineageRoutes` installs the routes and records every request so a
 * test can assert what was (not) fetched.
 */

export const PROJECT_ID = "showcase-project";
export const SRC = "source.demo.shopify.refunds";
export const STG = "model.demo.stg_refunds";
export const FCT = "model.demo.fct_orders";
export const MART = "model.demo.mart_orders_daily";

const parentMap: Record<string, string[]> = { [SRC]: [], [STG]: [SRC], [FCT]: [STG], [MART]: [FCT] };
const childMap: Record<string, string[]> = { [SRC]: [STG], [STG]: [FCT], [FCT]: [MART], [MART]: [] };

const mapInfo = (updated_at = 1_700_000_000) => ({
  id: "map-1",
  project_id: PROJECT_ID,
  branch: "main",
  revision: 3,
  status: "success",
  trigger: "manual",
  error: null,
  dbt_version: "1.9.0",
  node_count: 4,
  manifest_bytes: 1024,
  created_at: 1_700_000_000,
  updated_at,
});

const skelNode = (name: string, path: string, column_count: number) => ({
  name,
  resource_type: "model",
  path,
  fqn: ["demo", ...path.replace(/\.sql$/, "").split("/")],
  schema: "analytics",
  database: "demo",
  description: `${name} model`,
  tags: [],
  config: { materialized: "table" },
  column_count,
  tests: [{ name: `unique_${name}_id`, test_metadata: { name: "unique", kwargs: { column_name: "id" } } }],
});

const nodes = {
  [STG]: skelNode("stg_refunds", "staging/stg_refunds.sql", 3),
  [FCT]: skelNode("fct_orders", "facts/fct_orders.sql", 4),
  [MART]: skelNode("mart_orders_daily", "marts/mart_orders_daily.sql", 2),
};
const sources = {
  [SRC]: { name: "refunds", resource_type: "source", schema: "shopify", database: "raw", column_count: 2 },
};

export const COLUMNS: Record<string, { name: string; description?: string; data_type?: string }[]> = {
  [SRC]: [{ name: "refund_id", data_type: "int" }, { name: "amount", data_type: "numeric" }],
  [STG]: [
    { name: "refund_id", data_type: "int" },
    { name: "order_id", data_type: "int" },
    { name: "refund_amount", description: "net of fees", data_type: "numeric" },
  ],
  [FCT]: [
    { name: "order_id", data_type: "int" },
    { name: "gross", data_type: "numeric" },
    { name: "refunds", data_type: "numeric" },
    { name: "net", data_type: "numeric" },
  ],
  [MART]: [{ name: "day", data_type: "date" }, { name: "net_revenue", data_type: "numeric" }],
};

export const SQL: Record<string, { raw_sql: string; compiled_sql: string | null }> = {
  [STG]: {
    raw_sql: "select refund_id, order_id, amount as refund_amount\nfrom {{ source('shopify', 'refunds') }}",
    compiled_sql: "select refund_id, order_id, amount as refund_amount\nfrom raw.shopify.refunds",
  },
  [FCT]: {
    raw_sql: "select order_id, sum(refund_amount) as refunds\nfrom {{ ref('stg_refunds') }}\ngroup by 1",
    compiled_sql: "select order_id, sum(refund_amount) as refunds\nfrom demo.analytics.stg_refunds\ngroup by 1",
  },
  [MART]: {
    raw_sql: "select day, sum(net) as net_revenue from {{ ref('fct_orders') }} group by 1",
    compiled_sql: null,
  },
};

export function skeletonResponse(updated_at?: number) {
  return {
    status: "success",
    map: mapInfo(updated_at),
    graph: {
      metadata: { project_name: "demo", dbt_version: "1.9.0", variant: "skeleton" },
      nodes,
      sources,
      parent_map: parentMap,
      child_map: childMap,
    },
  };
}

/** The whole chain is every model's cone here, so one body serves all refs. */
export function coneResponse(ref: string) {
  const id = Object.keys(nodes).find((k) => k === ref || k.endsWith(`.${ref}`));
  if (!id) return null;
  return {
    status: "success",
    map: mapInfo(),
    model: { unique_id: id, ...nodes[id as keyof typeof nodes], columns: COLUMNS[id] },
    graph: {
      metadata: { project_name: "demo", dbt_version: "1.9.0", variant: "cone" },
      nodes,
      sources,
      parent_map: parentMap,
      child_map: childMap,
    },
    cone: {
      upstream: Object.keys(parentMap).filter((k) => k !== id),
      downstream: [],
    },
  };
}

export const fakeProjects = {
  projects: [
    {
      id: PROJECT_ID,
      org_id: "org-1",
      name: "demo",
      display_name: "Demo warehouse",
      description: null,
      source: "github",
      connection_name: null,
      status: "active",
      tags: null,
      settings: null,
      file_count: 4,
      total_bytes: 4096,
      default_branch: "main",
      created_by: null,
    },
  ],
  total: 1,
};

export interface LineageMockOptions {
  /** Hold the skeleton reply this long so the cone paints first. */
  skeletonDelayMs?: number;
  /** Hold the projects list too (the page must not wait for it). */
  projectsDelayMs?: number;
  /** Answer the cone endpoint with this status (simulate an old gateway). */
  coneStatus?: number;
}

export interface LineageMock {
  /** Request paths (pathname + search) in arrival order. */
  requests: string[];
  count(pattern: RegExp): number;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function mockLineageRoutes(
  context: BrowserContext,
  { skeletonDelayMs = 0, projectsDelayMs = 0, coneStatus = 200 }: LineageMockOptions = {},
): Promise<LineageMock> {
  const requests: string[] = [];
  const record = (route: Route) => {
    const u = new URL(route.request().url());
    requests.push(u.pathname + u.search);
  };
  await context.route("**/api/workspace-projects?status=active", async (route) => {
    record(route);
    if (projectsDelayMs) await sleep(projectsDelayMs);
    await route.fulfill({ json: fakeProjects });
  });
  await context.route(`**/api/workspace-projects/${PROJECT_ID}/dbt-map**`, async (route) => {
    record(route);
    const u = new URL(route.request().url());
    const path = u.pathname;
    const sqlMatch = /\/dbt-map\/model\/([^/]+)\/sql$/.exec(path);
    if (sqlMatch) {
      const ref = decodeURIComponent(sqlMatch[1]);
      const id = Object.keys(SQL).find((k) => k === ref || k.endsWith(`.${ref}`));
      if (!id) return route.fulfill({ status: 404, json: { detail: "no sql for this node" } });
      const node = nodes[id as keyof typeof nodes];
      return route.fulfill({
        json: {
          unique_id: id,
          name: node.name,
          path: node.path,
          original_file_path: `models/${node.path}`,
          language: "sql",
          ...SQL[id],
          source: "manifest",
        },
      });
    }
    const coneMatch = /\/dbt-map\/model\/([^/]+)$/.exec(path);
    if (coneMatch) {
      if (coneStatus !== 200) return route.fulfill({ status: coneStatus, json: { detail: "Not Found" } });
      const body = coneResponse(decodeURIComponent(coneMatch[1]));
      if (!body) return route.fulfill({ status: 404, json: { detail: "unknown model" } });
      return route.fulfill({ json: body });
    }
    if (path.endsWith("/dbt-map/columns")) {
      const ids = (u.searchParams.get("nodes") ?? "").split(",").filter(Boolean);
      return route.fulfill({ json: { columns: Object.fromEntries(ids.map((id) => [id, COLUMNS[id] ?? []])) } });
    }
    if (u.searchParams.get("include_graph") === "false") {
      return route.fulfill({ json: { status: "success", map: mapInfo(), graph: null } });
    }
    if (skeletonDelayMs) await sleep(skeletonDelayMs);
    return route.fulfill({ json: skeletonResponse() });
  });
  return {
    requests,
    count: (pattern) => requests.filter((r) => pattern.test(r)).length,
  };
}
