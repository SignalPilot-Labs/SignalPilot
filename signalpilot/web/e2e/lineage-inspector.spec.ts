import { expect, test, type Locator, type Page } from "@playwright/test";

import { PROJECT_ID, mockLineageRoutes } from "./lineage-fixtures";

/**
 * The resizable lineage inspector on /lineage/<model> against the fixture
 * gateway (local mode): drag the left-edge handle, persistence across a
 * reload, double-click reset, keyboard steps, the expand toggle, the SQL
 * tab filling the width, and the left panel yielding to a rail.
 */

const BASE = process.env.SP_WEB_BASE_URL ?? "http://localhost:3200";
const DEEP_LINK = `${BASE}/lineage/stg_refunds?project=${PROJECT_ID}`;
const WIDTH_KEY = "sp:lineage-inspector-width";

const widthOf = async (loc: Locator) => (await loc.boundingBox())!.width;

async function openInspector(page: Page) {
  await page.goto(DEEP_LINK);
  const root = page.getByTestId("lineage-page");
  await expect(root).toHaveAttribute("data-graph", "full");
  await root.locator(".react-flow__node").filter({ hasText: "fct_orders" }).first().click();
  const inspector = root.getByTestId("lineage-inspector");
  await expect(inspector).toBeVisible();
  // The row (panel + canvas + inspector) sits beside the app shell, so the
  // bounds derive from it rather than from the viewport.
  const row = Math.round(await widthOf(root.getByTestId("lineage-row")));
  return {
    root,
    inspector,
    row,
    max: row - 240 - 36,
    canvas: root.getByTestId("lineage-canvas"),
    handle: root.getByTestId("inspector-resize-handle"),
  };
}

async function dragHandle(page: Page, handle: Locator, dx: number) {
  const box = (await handle.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  // A few steps so the rAF-throttled preview runs mid-drag too.
  await page.mouse.move(x + dx / 2, y, { steps: 4 });
  await page.mouse.move(x + dx, y, { steps: 4 });
  await page.mouse.up();
}

test.describe("lineage inspector resize", () => {
  test.beforeEach(async ({ page, context }) => {
    await page.setViewportSize({ width: 1600, height: 900 });
    await mockLineageRoutes(context);
    // Clear the preference once (an init script would also wipe it on the
    // reload the persistence test relies on).
    await page.goto(`${BASE}/lineage`);
    await page.evaluate((key) => localStorage.removeItem(key), WIDTH_KEY);
  });

  test.afterEach(async ({ context }) => {
    await context.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("drag widens the inspector, shrinks the canvas, persists, and double-click resets", async ({ page }) => {
    const { inspector, canvas, handle, max } = await openInspector(page);
    const startWidth = await widthOf(inspector);
    const startCanvas = await widthOf(canvas);
    expect(startWidth).toBe(560);
    await expect(handle).toHaveAttribute("role", "separator");
    await expect(handle).toHaveAttribute("aria-orientation", "vertical");
    await expect(handle).toHaveAttribute("aria-valuenow", "560");
    await expect(handle).toHaveAttribute("aria-valuemin", "320");
    await expect(handle).toHaveAttribute("aria-valuemax", String(max));

    await dragHandle(page, handle, -400);
    await expect.poll(() => widthOf(inspector)).toBe(startWidth + 400);
    // The canvas gave the width up; the left panel yielded to the rail as
    // the canvas neared its reserve, so it shrank by less than the drag.
    const canvasAfter = await widthOf(canvas);
    expect(canvasAfter).toBeLessThan(startCanvas);
    expect(canvasAfter).toBeGreaterThanOrEqual(240);
    await expect(page.getByTestId("lineage-panel-rail")).toBeVisible();
    await expect(handle).toHaveAttribute("aria-valuenow", String(startWidth + 400));
    expect(await page.evaluate((k) => localStorage.getItem(k), WIDTH_KEY)).toBe(String(startWidth + 400));

    // Persisted: a reload comes back at the dragged width.
    await page.reload();
    const again = await openInspector(page);
    await expect.poll(() => widthOf(again.inspector)).toBe(startWidth + 400);

    // Double-click resets to the default and clears the preference.
    await again.handle.dblclick();
    await expect.poll(() => widthOf(again.inspector)).toBe(560);
    expect(await page.evaluate((k) => localStorage.getItem(k), WIDTH_KEY)).toBeNull();
  });

  test("the stored width is clamped to the viewport", async ({ page }) => {
    await page.addInitScript((key) => localStorage.setItem(key, "5000"), WIDTH_KEY);
    const { inspector, canvas, row, max } = await openInspector(page);
    await expect.poll(() => widthOf(inspector)).toBe(max);
    // The left panel collapsed to the rail; the canvas keeps its reserve.
    await expect(page.getByTestId("lineage-panel-rail")).toBeVisible();
    expect(await widthOf(canvas)).toBeGreaterThanOrEqual(240);
    await page.getByRole("button", { name: "Show lineage panel" }).click();
    await expect(page.getByTestId("lineage-panel-rail")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "raw tables" })).toBeVisible();
    await expect.poll(() => widthOf(inspector)).toBe(row - 288 - 240);
  });

  test("keyboard resizes on the separator", async ({ page }) => {
    const { inspector, handle, max } = await openInspector(page);
    await handle.focus();
    await page.keyboard.press("ArrowLeft");
    await expect.poll(() => widthOf(inspector)).toBe(592);
    await page.keyboard.press("Shift+ArrowLeft");
    await expect.poll(() => widthOf(inspector)).toBe(720);
    await page.keyboard.press("ArrowRight");
    await expect.poll(() => widthOf(inspector)).toBe(688);
    await page.keyboard.press("Shift+ArrowRight");
    await expect.poll(() => widthOf(inspector)).toBe(560);
    await page.keyboard.press("Home");
    await expect.poll(() => widthOf(inspector)).toBe(320);
    await page.keyboard.press("End");
    await expect.poll(() => widthOf(inspector)).toBe(max);
    expect(await page.evaluate((k) => localStorage.getItem(k), WIDTH_KEY)).toBe(String(max));
  });

  test("the expand toggle widens to the preset and the SQL block fills the width", async ({ page }) => {
    const { root, inspector, handle, row } = await openInspector(page);
    const wide = Math.round(row * 0.7);
    const expand = root.getByTestId("inspector-expand");
    await expect(expand).toHaveAttribute("aria-pressed", "false");
    await expand.click();
    await expect.poll(() => widthOf(inspector)).toBe(wide);
    await expect(expand).toHaveAttribute("aria-pressed", "true");
    await expect(inspector).toHaveAttribute("data-wide", "1");

    // The SQL block tracks the inspector width (padding aside).
    await root.getByTestId("inspector-tab-sql").click();
    const sql = root.getByTestId("inspector-sql");
    await expect(sql.locator("pre")).toContainText("ref('stg_refunds')");
    // Width minus the 24 px padding and the 1 px left border.
    const code = root.getByTestId("inspector-sql-code");
    expect(await widthOf(code)).toBe(wide - 25);
    await page.screenshot({ path: "test-results/lineage-inspector-sql-wide.png" });
    // The header keeps toggle, path and copy on one row at this width.
    const toggle = sql.getByRole("group", { name: "SQL variant" });
    const path = root.getByTestId("inspector-sql-path");
    const copy = sql.getByRole("button", { name: "Copy" });
    const rowY = (await toggle.boundingBox())!.y;
    expect(Math.abs((await path.boundingBox())!.y - rowY)).toBeLessThan(8);
    expect(Math.abs((await copy.boundingBox())!.y - rowY)).toBeLessThan(8);

    // Drag narrower: the block follows.
    await dragHandle(page, handle, 300);
    await expect.poll(() => widthOf(inspector)).toBe(wide - 300);
    expect(await widthOf(code)).toBe(wide - 300 - 25);

    // The toggle restores the width from before the preset.
    await expand.click();
    await expect.poll(() => widthOf(inspector)).toBe(wide);
    await expand.click();
    await expect.poll(() => widthOf(inspector)).toBe(wide - 300);
  });
});
