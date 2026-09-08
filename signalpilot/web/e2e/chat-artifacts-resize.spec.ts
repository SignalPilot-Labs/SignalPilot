import { expect, test, type Page } from "@playwright/test";

/**
 * Dragging the artifacts panel's left edge resizes it, the width survives a
 * reload, and a double-click puts it back. Driven through the fixture
 * harness at /chats/test, so no gateway is involved.
 *
 * The panel can never take the whole row: the width rules keep a reserve
 * for the transcript (components/chat/artifacts-panel-width.ts), so these
 * tests run on a wide viewport where a drag has room to move.
 */

const BASE = process.env.SP_WEB_BASE_URL ?? "http://localhost:3200";
const at = (ms: number) => `${BASE}/chats/test?at=${ms}&paused=1`;
/** Late enough that the notebook is live and files exist. */
const OPEN_AT_MS = 21_000;
/** Mirrors TRANSCRIPT_RESERVE in the width rules. */
const TRANSCRIPT_RESERVE = 420;

test.use({ viewport: { width: 1800, height: 900 } });

async function panelWidth(page: Page): Promise<number> {
  const box = await page.getByTestId("live-notebook-panel").boundingBox();
  if (!box) throw new Error("The artifacts panel is not visible");
  return Math.round(box.width);
}

async function openPanel(page: Page) {
  await page.goto(at(OPEN_AT_MS));
  // The page renders the harness twice (desktop and narrow shells); the
  // first is the one under test.
  await expect(
    page.getByTestId("chat-test-harness").first(),
  ).toHaveAttribute("data-hydrated", "1");
  const toggle = page.getByTestId("live-notebook-toggle");
  if (await toggle.count()) await toggle.first().click();
  await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
}

/** Drags the handle by `dx` (negative widens: the handle is on the left). */
async function dragHandle(page: Page, dx: number) {
  const handle = page.getByTestId("artifacts-resize-handle");
  const box = await handle.boundingBox();
  if (!box) throw new Error("The resize handle is not visible");
  const y = box.y + box.height / 2;
  const x = box.x + box.width / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx, y, { steps: 12 });
  await page.mouse.up();
}

// Each test gets a fresh browser context, so the stored width starts empty
// on its own; clearing it per navigation would defeat the reload check.
test.describe("artifacts panel resize", () => {
  test("dragging the handle widens the panel and the width persists", async ({
    page,
  }) => {
    await openPanel(page);
    const before = await panelWidth(page);

    await dragHandle(page, -160);
    const wider = await panelWidth(page);
    expect(wider).toBeGreaterThan(before + 100);

    // The committed width comes back on the next load.
    await openPanel(page);
    expect(Math.abs((await panelWidth(page)) - wider)).toBeLessThanOrEqual(4);
  });

  test("dragging back narrows it, and double-click restores the default", async ({
    page,
  }) => {
    await openPanel(page);
    const initial = await panelWidth(page);

    await dragHandle(page, 120);
    expect(await panelWidth(page)).toBeLessThan(initial - 80);

    await page.getByTestId("artifacts-resize-handle").dblclick();
    expect(Math.abs((await panelWidth(page)) - initial)).toBeLessThanOrEqual(4);
  });

  test("the drag stops before it would squeeze the transcript out", async ({
    page,
  }) => {
    await openPanel(page);
    await dragHandle(page, -4000);
    const width = await panelWidth(page);
    const row = await page
      .getByTestId("live-notebook-panel")
      .evaluate((element) => element.parentElement?.clientWidth ?? 0);
    expect(row).toBeGreaterThan(0);
    expect(width).toBeLessThanOrEqual(row - TRANSCRIPT_RESERVE);
  });

  test("the separator resizes from the keyboard", async ({ page }) => {
    await openPanel(page);
    const before = await panelWidth(page);
    const handle = page.getByTestId("artifacts-resize-handle");
    await handle.focus();
    await handle.press("ArrowLeft");
    await handle.press("ArrowLeft");
    expect(await panelWidth(page)).toBe(before + 64);
    await handle.press("Home");
    expect(await panelWidth(page)).toBe(360);
  });
});
