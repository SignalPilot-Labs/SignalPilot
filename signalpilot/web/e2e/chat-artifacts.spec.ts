import { expect, test } from "@playwright/test";

/**
 * Artifacts panel tabs on the standalone chat surface, exercised through the
 * fixture harness at /chats/test (no model, gateway, or warehouse needed).
 *
 * Fixture timeline (lib/chat-test-fixture.ts):
 * -  7 400ms  governed query completes → one SQL trace execution
 * -  8 720ms  notebook_started → notebook resource goes live
 * -  9 200ms  Write tool → one conversation file (analysis/q3_growth.py)
 * - 12 100ms+ export writes → report.html, chart.svg, csv land by 14 050ms;
 *             a markdown summary follows at 15 460ms (five files total)
 * - 20 800ms  archive_completed → second ("forecast") notebook lands
 *
 * The harness stubs both inner viewers (notebook + file) so the specs cover
 * panel structure, not the viewer internals.
 */

const BASE = process.env.SP_WEB_BASE_URL ?? "http://localhost:3200";
const at = (ms: number) => `${BASE}/chats/test?at=${ms}&paused=1`;

/** Clicks before React hydration are silently lost — gate on the harness flag. */
async function waitForHydration(page: import("@playwright/test").Page) {
  await expect(page.getByTestId("chat-test-harness")).toHaveAttribute(
    "data-hydrated",
    "1",
  );
}

test.describe("artifacts panel (fixture harness)", () => {
  test("toggle is absent before any artifacts exist", async ({ page }) => {
    // Mid-run, but the query has not completed and nothing was written yet.
    await page.goto(at(3_000));
    await expect(page.getByTestId("chat-activity-group").first()).toBeVisible();
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
    await expect(page.getByTestId("live-notebook-toggle")).toHaveCount(0);
  });

  test("queries alone make the panel reachable, defaulting to Queries", async ({
    page,
  }) => {
    // 7.5s: the governed query completed but no notebook or files exist.
    await page.goto(at(7_500));
    await waitForHydration(page);
    const toggle = page.getByTestId("live-notebook-toggle");
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    // No notebook and no files: the Queries tab is the default.
    await expect(page.getByTestId("sql-trace-panel")).toBeVisible();
    await expect(page.getByTestId("sql-trace-row")).toHaveCount(1);
  });

  test("tabs render with counts and the notebook tab stays the default", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    await page.getByTestId("live-notebook-toggle").click();
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    // All three tabs are present; Files and Queries carry count chips.
    await expect(page.getByTestId("artifacts-tab-notebook")).toBeVisible();
    await expect(page.getByTestId("artifacts-tab-files")).toContainText("5");
    await expect(page.getByTestId("artifacts-tab-queries")).toContainText("1");
    // The notebook has content, so its tab is active by default.
    await expect(page.getByTestId("live-notebook-inline")).toBeVisible();
    await expect(page.getByTestId("chat-notebook-stub")).toBeVisible();
  });

  test("files tab lists the written file and opens the viewer", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    await page.getByTestId("live-notebook-toggle").click();
    await page.getByTestId("artifacts-tab-files").click();
    const rows = page.getByTestId("artifacts-file-row");
    await expect(rows).toHaveCount(5);
    const row = rows.filter({ hasText: "q3_growth.py" });
    await expect(row).toHaveCount(1);
    await row.click();
    // The harness stubs the file viewer; a back affordance returns to the list.
    await expect(page.getByTestId("chat-file-stub")).toBeVisible();
    await page.getByTestId("artifacts-file-back").click();
    await expect(page.getByTestId("artifacts-file-row")).toHaveCount(5);
  });

  test("multiple notebooks render a chip strip that switches the view", async ({
    page,
  }) => {
    // Mid-run only the analysis notebook exists: no chip strip.
    await page.goto(at(9_000));
    await waitForHydration(page);
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await expect(page.getByTestId("artifacts-notebook-chip")).toHaveCount(0);
    // At the end the fixture's second ("forecast") notebook has landed.
    await page.goto(at(24_800));
    await waitForHydration(page);
    await page.getByTestId("live-notebook-toggle").click();
    const chips = page.getByTestId("artifacts-notebook-chip");
    await expect(chips).toHaveCount(2);
    await expect(chips.nth(0)).toContainText("analysis");
    await expect(chips.nth(0)).toHaveAttribute("aria-pressed", "true");
    await expect(chips.nth(1)).toContainText("forecast");
    await expect(chips.nth(1)).toHaveAttribute("aria-pressed", "false");
    // The active-notebook container is unique and carries the inline testid.
    await expect(page.getByTestId("live-notebook-inline")).toHaveCount(1);
    await expect(page.getByTestId("chat-notebook-stub")).toBeVisible();
    // Switching moves the selection and keeps a single active container.
    await chips.nth(1).click();
    await expect(chips.nth(1)).toHaveAttribute("aria-pressed", "true");
    await expect(chips.nth(0)).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("live-notebook-inline")).toHaveCount(1);
    await expect(page.getByTestId("chat-notebook-stub")).toBeVisible();
  });

  test("queries tab shows the completed governed execution", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    await page.getByTestId("live-notebook-toggle").click();
    await page.getByTestId("artifacts-tab-queries").click();
    await expect(page.getByTestId("sql-trace-panel")).toBeVisible();
    await expect(page.getByTestId("sql-trace-row")).toHaveCount(1);
    await expect(page.getByTestId("sql-trace-row")).toContainText(
      "warehouse_prod",
    );
  });
});
