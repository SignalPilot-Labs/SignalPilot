import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";

import { FCT, mockLineageRoutes } from "./lineage-fixtures";

/**
 * The chat agent links dbt models as /lineage/<model>?project=<id>. A plain
 * click on such a link opens the lineage modal over the chat instead of
 * navigating; the URL stays put and "Open full page" keeps the real route.
 *
 * Runs against the /chats/markdown playground, whose prose section carries
 * one such link. The map itself needs gateway data a local-mode server does
 * not have, so the first tests accept either the embedded map or the modal's
 * error state (both keep the full-page link), and the mocked tests drive the
 * real graph inside the modal against the fixture gateway (lineage-fixtures).
 *
 * Against a cloud-mode server /chats is Clerk-protected: point
 * SP_E2E_STATE_FILE at a minted state file (see chat-markdown.spec.ts).
 */

const BASE = process.env.SP_WEB_BASE_URL ?? "http://localhost:3200";
const LINK_HREF = "/lineage/stg_refunds?project=showcase-project";

interface E2EState {
  org_id: string;
  sign_in_tickets?: string[];
}

const statePath = process.env.SP_E2E_STATE_FILE;
const state: E2EState | null = statePath
  ? (JSON.parse(fs.readFileSync(statePath, "utf8")) as E2EState)
  : null;

async function signIn(page: Page, s: E2EState): Promise<void> {
  const ticket = s.sign_in_tickets?.[0];
  if (!ticket) throw new Error("state file has no sign_in_tickets");
  await page.goto(`${BASE}/sign-in`);
  await page.waitForFunction(() =>
    Boolean((window as unknown as { Clerk?: { loaded?: boolean } }).Clerk?.loaded),
  );
  await page.evaluate(
    async ({ t, orgId }) => {
      const clerk = (window as unknown as { Clerk: any }).Clerk;
      const result = await clerk.client.signIn.create({ strategy: "ticket", ticket: t });
      await clerk.setActive({ session: result.createdSessionId, organization: orgId });
    },
    { t: ticket, orgId: s.org_id },
  );
  await page
    .waitForURL(/dashboard|onboarding|projects/, { timeout: 20_000 })
    .catch(() => undefined);
}

async function openProse(page: Page): Promise<void> {
  await page.goto(`${BASE}/chats/markdown`);
  await expect(page.getByTestId("markdown-showcase")).toHaveAttribute("data-hydrated", "1");
  await page.getByTestId("showcase-section-prose").click();
}

test.describe.configure({ mode: "serial" });

test.describe("chat lineage modal", () => {
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage({ baseURL: BASE });
    if (state) await signIn(page, state);
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("a plain click opens the modal in place and Escape closes it", async () => {
    await openProse(page);
    const rendered = page.getByTestId("showcase-rendered");
    const link = rendered.locator(`a[href="${LINK_HREF}"]`);
    await expect(link).toHaveText("stg_refunds");
    const urlBefore = page.url();

    await link.click();
    const modal = page.getByTestId("lineage-modal");
    await expect(modal).toBeVisible();
    await expect(modal).toHaveAttribute("aria-modal", "true");
    await expect(page.getByTestId("lineage-modal-title")).toHaveText("stg_refunds");
    await expect(page.getByTestId("lineage-modal-open-page")).toHaveAttribute("href", LINK_HREF);
    expect(page.url()).toBe(urlBefore);
    await expect(page.locator("body")).toHaveCSS("overflow", "hidden");

    // Body: the embedded map when the gateway answers, else the error state.
    // Both keep a route to the full page.
    const body = page.getByTestId("lineage-embed").or(page.getByTestId("lineage-modal-error"));
    await expect(body.first()).toBeVisible({ timeout: 20_000 });
    const failed = await page.getByTestId("lineage-modal-error").isVisible();
    test.info().annotations.push({
      type: "lineage-body",
      description: failed ? "error state (no map data in this mode)" : "embedded map",
    });
    if (failed) {
      await expect(
        page.getByTestId("lineage-modal-error").locator(`a[href="${LINK_HREF}"]`),
      ).toBeVisible();
    }

    await page.keyboard.press("Escape");
    await expect(modal).toHaveCount(0);
    expect(page.url()).toBe(urlBefore);
    await expect(page.locator("body")).not.toHaveCSS("overflow", "hidden");
  });

  test("the backdrop and the close button also close it", async () => {
    await openProse(page);
    const link = page.getByTestId("showcase-rendered").locator(`a[href="${LINK_HREF}"]`);

    await link.click();
    await expect(page.getByTestId("lineage-modal")).toBeVisible();
    await page.getByTestId("lineage-modal-close").click();
    await expect(page.getByTestId("lineage-modal")).toHaveCount(0);

    await link.click();
    await expect(page.getByTestId("lineage-modal")).toBeVisible();
    await page.getByTestId("lineage-modal-backdrop").click({ position: { x: 4, y: 4 } });
    await expect(page.getByTestId("lineage-modal")).toHaveCount(0);
  });

  test("a modifier click opens the page in a new tab instead", async () => {
    await openProse(page);
    const link = page.getByTestId("showcase-rendered").locator(`a[href="${LINK_HREF}"]`);
    const popup = page.context().waitForEvent("page");
    await link.click({ modifiers: ["ControlOrMeta"] });
    const tab = await popup;
    await tab.waitForURL((url) => url.pathname + url.search === LINK_HREF);
    await tab.close();
    await expect(page.getByTestId("lineage-modal")).toHaveCount(0);
  });

  test("with map data the modal shows the interactive staged graph", async () => {
    const context = page.context();
    // The skeleton lags well behind the cone: the modal must paint the
    // focused view from the cone alone.
    const mock = await mockLineageRoutes(context, { skeletonDelayMs: 1500, projectsDelayMs: 1500 });
    try {
      await openProse(page);
      await page.evaluate(() => localStorage.removeItem("sp:lineage-inspector-width"));
      await page.getByTestId("showcase-rendered").locator(`a[href="${LINK_HREF}"]`).click();
      const modal = page.getByTestId("lineage-modal");
      await expect(modal).toBeVisible();
      const embed = page.getByTestId("lineage-embed");
      await expect(embed).toBeVisible();
      await expect(page.getByTestId("lineage-modal-error")).toHaveCount(0);

      // Cone first: the staged focus view is on screen while the skeleton
      // (and the projects list) are still in flight.
      const nodes = embed.locator(".react-flow__node");
      await expect(nodes.filter({ hasText: "stg_refunds" }).first()).toBeVisible();
      await expect(embed).toHaveAttribute("data-graph", "cone");
      await expect(embed).toHaveAttribute("data-focus-ready", "1");
      await expect(nodes.filter({ hasText: "fct_orders" }).first()).toBeVisible();
      await expect(nodes.filter({ hasText: "mart_orders_daily" }).first()).toBeVisible();
      await expect(embed.getByText("Staging", { exact: true }).first()).toBeVisible();
      await expect(embed.getByRole("button", { name: "raw tables" })).toBeVisible();
      expect(mock.count(/dbt-map\/model\/stg_refunds\?/)).toBe(1);
      expect(mock.count(/dbt-map\?graph=skeleton/)).toBe(1);

      // Then the skeleton swaps in silently.
      await expect(embed).toHaveAttribute("data-graph", "full", { timeout: 10_000 });
      await expect(nodes.filter({ hasText: "stg_refunds" }).first()).toBeVisible();

      // Zoom controls are live inside the dialog.
      const viewport = embed.locator(".react-flow__viewport");
      const before = await viewport.getAttribute("style");
      await embed.locator(".react-flow__controls-zoomin").click();
      await expect
        .poll(async () => viewport.getAttribute("style"))
        .not.toBe(before);

      // Selecting a node opens the inspector: columns arrive lazily for a
      // skeleton node, and the SQL tab fetches the model's body on demand.
      await nodes.filter({ hasText: "fct_orders" }).first().click();
      const columns = embed.getByTestId("inspector-columns");
      await expect(columns).toBeVisible();
      await expect(columns).toHaveAttribute("data-loaded", "1");
      await expect(columns.getByText("refund_amount").or(columns.getByText("gross")).first()).toBeVisible();
      expect(
        mock.requests.filter((r) => r.includes("/dbt-map/columns?") && r.includes(FCT)),
      ).toHaveLength(1);

      await embed.getByTestId("inspector-tab-sql").click();
      const sql = embed.getByTestId("inspector-sql");
      await expect(sql).toBeVisible();
      await expect(sql).toHaveAttribute("data-variant", "raw");
      await expect(sql.locator("pre")).toContainText("ref('stg_refunds')");
      await expect(embed.getByTestId("inspector-sql-path")).toHaveText("models/facts/fct_orders.sql");
      await sql.getByRole("button", { name: "compiled" }).click();
      await expect(sql.locator("pre")).toContainText("demo.analytics.stg_refunds");
      expect(mock.count(/dbt-map\/model\/[^/]+\/sql/)).toBe(1);

      // The inspector resizes inside the modal too: the default is a share
      // of the modal, a drag on the left-edge handle widens it and the
      // canvas gives the width up, and the code block follows.
      const inspector = embed.getByTestId("lineage-inspector");
      const canvas = embed.getByTestId("lineage-canvas");
      const handle = embed.getByTestId("inspector-resize-handle");
      const width = async (l: typeof inspector) => (await l.boundingBox())!.width;
      const embedWidth = await width(embed);
      const inspectorBefore = await width(inspector);
      const canvasBefore = await width(canvas);
      expect(inspectorBefore).toBe(Math.round(embedWidth * 0.45));
      const box = (await handle.boundingBox())!;
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width / 2 - 200, box.y + box.height / 2, { steps: 6 });
      await page.mouse.up();
      await expect.poll(() => width(inspector)).toBe(inspectorBefore + 200);
      // The canvas gave the width up, unless that would take it under its
      // reserve: then the left panel collapsed to a rail instead.
      const canvasAfter = await width(canvas);
      if (canvasBefore - 200 >= 240) expect(canvasAfter).toBe(canvasBefore - 200);
      else await expect(embed.getByTestId("lineage-panel-rail")).toBeVisible();
      expect(canvasAfter).toBeGreaterThanOrEqual(240);
      expect(await width(embed.getByTestId("inspector-sql-code"))).toBe(inspectorBefore + 200 - 25);
      await expect(modal).toBeVisible();
      await handle.dblclick();
      await expect.poll(() => width(inspector)).toBe(inspectorBefore);

      // The stg_refunds node already has its columns from the cone: no request.
      const columnCalls = mock.count(/dbt-map\/columns/);
      await nodes.filter({ hasText: "stg_refunds" }).first().click();
      await embed.getByTestId("inspector-tab-details").click();
      await expect(embed.getByTestId("inspector-columns")).toHaveAttribute("data-loaded", "1");
      expect(mock.count(/dbt-map\/columns/)).toBe(columnCalls);

      // The raw-tables tab swaps the panel without touching the URL.
      const url = page.url();
      await embed.getByRole("button", { name: "raw tables" }).click();
      await expect(embed.getByText("shopify.refunds", { exact: false }).first()).toBeVisible();
      expect(page.url()).toBe(url);

      await page.keyboard.press("Escape");
      await expect(modal).toHaveCount(0);
    } finally {
      await context.unrouteAll({ behavior: "ignoreErrors" });
    }
  });

  test("reopening the modal is served from the cache and an old gateway falls back", async () => {
    const context = page.context();
    const mock = await mockLineageRoutes(context, { coneStatus: 404 });
    try {
      await openProse(page);
      const link = page.getByTestId("showcase-rendered").locator(`a[href="${LINK_HREF}"]`);
      await link.click();
      const embed = page.getByTestId("lineage-embed");
      // The cone 404s (older gateway): the skeleton carries the view.
      await expect(embed).toHaveAttribute("data-graph", "full");
      await expect(embed.locator(".react-flow__node").filter({ hasText: "stg_refunds" }).first()).toBeVisible();
      const mapCalls = mock.count(/dbt-map/);
      await page.keyboard.press("Escape");

      // Second open: nothing is fetched again.
      await link.click();
      await expect(page.getByTestId("lineage-embed")).toHaveAttribute("data-graph", "full");
      await expect(page.getByTestId("lineage-embed")).toHaveAttribute("data-focus-ready", "1");
      expect(mock.count(/dbt-map/)).toBe(mapCalls);
      await page.keyboard.press("Escape");
    } finally {
      await context.unrouteAll({ behavior: "ignoreErrors" });
    }
  });

  test("a lineage link without a project stays a navigation", async () => {
    await openProse(page);
    const link = page.getByTestId("showcase-rendered").locator('a[href="/lineage/fct_orders"]');
    await expect(link).toBeVisible();
    await link.click();
    await page.waitForURL(/\/lineage\/fct_orders/);
    await expect(page.getByTestId("lineage-modal")).toHaveCount(0);
  });
});
