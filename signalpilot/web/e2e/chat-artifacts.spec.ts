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
 * - 15 700ms  run_cells saves artifacts/revenue_by_month.{png,csv}; the
 *             sandbox capture lists them at 20 600ms / 20 700ms (seven files)
 * - 20 000ms  the answer embeds the PNG inline; 20 650ms links the CSV
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
    await expect(page.getByTestId("artifacts-tab-files")).toContainText("7");
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
    await expect(rows).toHaveCount(7);
    const row = rows.filter({ hasText: "q3_growth.py" });
    await expect(row).toHaveCount(1);
    await row.click();
    // The harness stubs the file viewer; a back affordance returns to the list.
    await expect(page.getByTestId("chat-file-stub")).toBeVisible();
    await page.getByTestId("artifacts-file-back").click();
    await expect(page.getByTestId("artifacts-file-row")).toHaveCount(7);
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
    // The agent's query description headlines the row; the connection is
    // demoted to the secondary line.
    await expect(page.getByTestId("sql-trace-description")).toHaveText(
      "Comparing Q2 and Q3 revenue by region from fct_orders",
    );
  });
});

/**
 * Inline file references in the transcript (spec §8.8). The fixture answer
 * embeds `![Revenue by month](artifacts/revenue_by_month.png)` at 20.0s and
 * links `artifacts/revenue_by_month.csv` at 20.65s; the sandbox capture
 * announces the PNG at 20.6s and the CSV at 20.7s, so the figure is a
 * pending placeholder between 20.0s and 20.6s and a real image after.
 */
test.describe("inline file references (fixture harness)", () => {
  test("a referenced image is a pending placeholder before its file event", async ({
    page,
  }) => {
    // 20.3s: the answer already references the chart; the capture event
    // that lists it in the manifest lands at 20.6s.
    await page.goto(at(20_300));
    await waitForHydration(page);
    const pending = page.getByTestId("chat-md-figure-pending");
    await expect(pending).toHaveCount(1);
    await expect(pending).toHaveAttribute("aria-busy", "true");
    await expect(pending).toContainText("revenue_by_month.png");
    await expect(page.getByTestId("chat-md-figure")).toHaveCount(0);
  });

  test("the inline figure renders after the file event, captioned from alt", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    const figure = page.getByTestId("chat-md-figure");
    await expect(figure).toHaveCount(1);
    await expect(figure.locator("figcaption")).toHaveText("Revenue by month");
    await expect(page.getByTestId("chat-md-figure-pending")).toHaveCount(0);
    // Not a broken image: the PNG served through the object URL decoded.
    const img = figure.locator("img").first();
    await expect
      .poll(() => img.evaluate((node: HTMLImageElement) => node.naturalWidth))
      .toBeGreaterThan(0);
  });

  test("clicking the figure opens the lightbox on the same image", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    await page.getByTestId("chat-md-figure").locator("button").first().click();
    const lightbox = page.getByTestId("artifact-lightbox");
    await expect(lightbox).toBeVisible();
    await expect(lightbox).toContainText("revenue_by_month.png");
    await expect(lightbox.locator("img")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(lightbox).not.toBeVisible();
  });

  test("a linked data file renders a chip that opens the panel on that file", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    const chip = page.getByTestId("chat-md-file-chip");
    await expect(chip).toHaveCount(1);
    await expect(chip).toContainText("revenue_by_month.csv");
    await expect(chip).toContainText("Preview");
    await expect(chip).toHaveAttribute("data-kind", "data");
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
    await chip.click();
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await expect(page.getByTestId("artifacts-tab-files")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // The panel is focused on the CSV, not just any file.
    await expect(page.getByTestId("artifacts-file-view")).toHaveAttribute(
      "data-file-id",
      "file-fixture-revenue-csv",
    );
  });

  test("referenced and unreferenced files alike get a timeline card", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    const cards = page.getByTestId("chat-artifact-cards");
    await expect(cards).toBeVisible();
    // The inline figure and chip are one surface; the timeline card is
    // another. Both runtime files show in both places.
    await expect(cards).toContainText("revenue_by_month.png");
    await expect(cards).toContainText("revenue_by_month.csv");
    await expect(cards).toContainText("q3_growth.py");
    await expect(cards).toContainText("q3_summary.md");
    await expect(page.getByTestId("chat-md-figure")).toHaveCount(1);
    await expect(page.getByTestId("chat-md-file-chip")).toHaveCount(1);
    // The panel still lists every file.
    await page.getByTestId("live-notebook-toggle").click();
    await page.getByTestId("artifacts-tab-files").click();
    await expect(page.getByTestId("artifacts-file-row")).toHaveCount(7);
  });

  test("a missing image reference renders as a block band after the run ends", async ({
    page,
  }) => {
    // The tail narration at 24.5s embeds artifacts/q4_forecast.png, which
    // the run never saves. Once the run ends (24.6s) it is "missing".
    await page.goto(at(24_800));
    await waitForHydration(page);
    const band = page.getByTestId("chat-md-image-missing");
    await expect(band).toHaveCount(1);
    await expect(band).toHaveAttribute("role", "status");
    await expect(band).toContainText("Image not available");
    await expect(band).toContainText("q4_forecast.png");
    await expect(page.getByTestId("chat-md-figure-pending")).toHaveCount(0);
    // A block on its own line: it spans the transcript column, not the
    // width of its text.
    const bandBox = await band.boundingBox();
    const columnBox = await page
      .locator(".chat-markdown")
      .filter({ has: band })
      .last()
      .boundingBox();
    expect(bandBox).not.toBeNull();
    expect(columnBox).not.toBeNull();
    expect(bandBox!.width).toBeGreaterThan(columnBox!.width * 0.9);
    // Never the inline chip for an image reference.
    await expect(page.getByTestId("chat-md-file-chip-missing")).toHaveCount(0);
  });

  test("a missing reference is pending only while its own run streams", async ({
    page,
  }) => {
    // 24.55s: the reference landed, the run is still running.
    await page.goto(at(24_550));
    await waitForHydration(page);
    await expect(page.getByTestId("chat-md-figure-pending")).toHaveCount(1);
    await expect(page.getByTestId("chat-md-image-missing")).toHaveCount(0);
    // ?followup=1 appends a later turn whose run is queued. The earlier
    // message's reference must stay missing, not flip back to a shimmer.
    await page.goto(`${at(24_800)}&followup=1`);
    await waitForHydration(page);
    const messages = page.locator("[data-chat-message-id]");
    await expect(messages).toHaveCount(4);
    await expect(page.getByTestId("chat-live-indicator")).toHaveCount(1);
    await expect(page.getByTestId("chat-md-image-missing")).toHaveCount(1);
    await expect(page.getByTestId("chat-md-figure-pending")).toHaveCount(0);
    await expect(page.getByTestId("chat-md-figure")).toHaveCount(1);
  });

  test("/chats/markdown shows a not-available band for a relative image without a context", async ({
    page,
  }) => {
    await page.goto(`${BASE}/chats/markdown`);
    await expect(page.getByTestId("markdown-showcase")).toHaveAttribute(
      "data-hydrated",
      "1",
    );
    await page.getByTestId("showcase-section-media").click();
    const rendered = page.getByTestId("showcase-rendered");
    // No conversation: there is no manifest to resolve against, so the
    // reference renders as the "not available" band — never a broken
    // image (no figure, no placeholder, no file chip).
    const missing = rendered.getByTestId("chat-md-image-missing");
    await expect(missing).toHaveCount(2);
    await expect(missing.first()).toContainText("revenue_by_month.png");
    await expect(
      rendered.locator('img[src$="artifacts/revenue_by_month.png"]'),
    ).toHaveCount(0);
    await expect(rendered.getByTestId("chat-md-figure")).toHaveCount(0);
    await expect(rendered.getByTestId("chat-md-figure-pending")).toHaveCount(0);
    await expect(rendered.getByTestId("chat-md-file-chip")).toHaveCount(0);
    await expect(
      rendered.locator('a[href$="artifacts/revenue_by_month.csv"]'),
    ).toHaveCount(1);
    await expect(rendered).not.toContainText("[blocked]");
  });
});
