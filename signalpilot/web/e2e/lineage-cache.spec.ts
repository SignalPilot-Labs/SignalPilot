import { expect, test } from "@playwright/test";

import { PROJECT_ID, mockLineageRoutes } from "./lineage-fixtures";

/**
 * /lineage/<model>?project=<id> against the fixture gateway, in local mode:
 * the deep link paints from the cone before the skeleton or the projects
 * list arrive, model-to-model focus changes refetch nothing, columns and
 * SQL load lazily on selection, and the time to the focused node is
 * measured from navigation start via the page's performance mark.
 */

const BASE = process.env.SP_WEB_BASE_URL ?? "http://localhost:3200";
const DEEP_LINK = `${BASE}/lineage/stg_refunds?project=${PROJECT_ID}`;

async function focusReadyMs(page: import("@playwright/test").Page): Promise<number> {
  return page.evaluate(() => {
    const [m] = performance.getEntriesByName("sp:lineage:focus-ready");
    return m ? Math.round(m.startTime) : -1;
  });
}

test.describe("lineage page cache", () => {
  test.afterEach(async ({ context }) => {
    await context.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("a deep link paints from the cone before the skeleton and the projects list", async ({
    page,
    context,
  }) => {
    const mock = await mockLineageRoutes(context, { skeletonDelayMs: 2000, projectsDelayMs: 2000 });
    await page.goto(DEEP_LINK);
    const root = page.getByTestId("lineage-page");
    await expect(root).toHaveAttribute("data-focus-ready", "1");
    await expect(root).toHaveAttribute("data-graph", "cone");
    const nodes = root.locator(".react-flow__node");
    await expect(nodes.filter({ hasText: "stg_refunds" }).first()).toBeVisible();
    await expect(root.getByText("Staging", { exact: true }).first()).toBeVisible();

    // Cone, skeleton and projects all left together; none waited on another.
    // (Dev StrictMode may double the projects effect; the count is >= 1.)
    expect(mock.count(/dbt-map\/model\/stg_refunds\?/)).toBe(1);
    expect(mock.count(/dbt-map\?graph=skeleton/)).toBe(1);
    expect(mock.count(/workspace-projects\?status=active/)).toBeGreaterThanOrEqual(1);
    const ready = await focusReadyMs(page);
    test.info().annotations.push({ type: "focus-ready-ms (skeleton held 2 s)", description: String(ready) });
    expect(ready).toBeGreaterThan(0);
    expect(ready).toBeLessThan(2000);

    await expect(root).toHaveAttribute("data-graph", "full", { timeout: 10_000 });
    await expect(nodes.filter({ hasText: "stg_refunds" }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "dbt map" })).toBeVisible();
  });

  test("focusing another model refetches nothing and columns and SQL load on selection", async ({
    page,
    context,
  }) => {
    const mock = await mockLineageRoutes(context);
    await page.goto(DEEP_LINK);
    const root = page.getByTestId("lineage-page");
    await expect(root).toHaveAttribute("data-graph", "full");
    const nodes = root.locator(".react-flow__node");
    const ready = await focusReadyMs(page);
    test.info().annotations.push({ type: "focus-ready-ms (no delays)", description: String(ready) });
    // Graph requests only: skeleton, cone, full map (columns and SQL are lazy by design).
    const graphCalls = () =>
      mock.requests.filter((r) => r.includes("/dbt-map") && !r.includes("/columns") && !/\/sql(\?|$)/.test(r)).length;
    const mapCalls = graphCalls();

    // Select fct_orders and Focus it: URL rewrites, no graph request leaves.
    await nodes.filter({ hasText: "fct_orders" }).first().click();
    await expect(root.getByTestId("inspector-columns")).toHaveAttribute("data-loaded", "1");
    const columnCallsBefore = mock.count(/dbt-map\/columns\?nodes=/);
    await root.getByRole("button", { name: "Focus", exact: true }).click();
    await expect.poll(() => new URL(page.url()).pathname).toBe("/lineage/fct_orders");
    expect(new URL(page.url()).searchParams.get("project")).toBe(PROJECT_ID);
    await expect(nodes.filter({ hasText: "fct_orders" }).first()).toBeVisible();
    expect(graphCalls()).toBe(mapCalls);

    // Select a skeleton node: its columns come through the columns endpoint.
    await nodes.filter({ hasText: "mart_orders_daily" }).first().click();
    const columns = root.getByTestId("inspector-columns");
    await expect(columns).toHaveAttribute("data-loaded", "1");
    await expect(columns.getByText("net_revenue")).toBeVisible();
    expect(mock.count(/dbt-map\/columns\?nodes=/)).toBe(columnCallsBefore + 1);
    expect(mock.requests.some((r) => r.includes("/dbt-map/columns?") && r.includes("mart_orders_daily"))).toBe(true);

    // The SQL tab fetches once per node and shows the raw body.
    await root.getByTestId("inspector-tab-sql").click();
    const sql = root.getByTestId("inspector-sql");
    await expect(sql.locator("pre")).toContainText("ref('fct_orders')");
    // No compiled body for the mart: the toggle stays hidden.
    await expect(sql.getByRole("button", { name: "compiled" })).toHaveCount(0);
    expect(mock.count(/dbt-map\/model\/[^/]+\/sql/)).toBe(1);

    // Switching nodes (via the focus panel rows) with the SQL tab open
    // fetches each node's SQL once.
    const row = (name: string) => root.getByRole("button", { name, exact: true });
    await row("fct_orders").click();
    await expect(root.getByTestId("inspector-sql").locator("pre")).toContainText("ref('stg_refunds')");
    expect(mock.count(/dbt-map\/model\/[^/]+\/sql/)).toBe(2);
    await row("mart_orders_daily").click();
    await expect(root.getByTestId("inspector-sql").locator("pre")).toContainText("ref('fct_orders')");
    expect(mock.count(/dbt-map\/model\/[^/]+\/sql/)).toBe(2);

    // A source node has no SQL: the quiet state, and no request.
    await row("refunds").click();
    await expect(root.getByTestId("inspector-sql-unavailable")).toBeVisible();
    expect(mock.count(/dbt-map\/model\/[^/]+\/sql/)).toBe(2);
  });

  test("an older gateway without the cone endpoint still renders the deep link", async ({
    page,
    context,
  }) => {
    const mock = await mockLineageRoutes(context, { coneStatus: 404 });
    await page.goto(DEEP_LINK);
    const root = page.getByTestId("lineage-page");
    await expect(root).toHaveAttribute("data-focus-ready", "1");
    await expect(root).toHaveAttribute("data-graph", "full");
    await expect(root.locator(".react-flow__node").filter({ hasText: "stg_refunds" }).first()).toBeVisible();
    expect(mock.count(/dbt-map\/model\/stg_refunds\?/)).toBe(1);
    expect(mock.count(/dbt-map\?graph=skeleton/)).toBe(1);
  });
});
