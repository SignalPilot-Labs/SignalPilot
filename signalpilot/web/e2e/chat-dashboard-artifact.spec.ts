import { expect, test } from "@playwright/test";

/**
 * Dashboard artifacts on the standalone chat surface, exercised through the
 * fixture harness at /chats/test (no model, gateway, or warehouse needed).
 *
 * Fixture timeline (lib/chat-test-fixture-dashboard.ts):
 * - 20 720ms  the answer links `artifacts/revenue.dashboard.json`
 * - 20 730ms  dashboard_load_published pulls the published "Revenue
 *             overview" (slug `revenue`, v3) into the sandbox (done at 20 745ms)
 * - 20 750ms  the sandbox capture lists the spec and its three dataset
 *             snapshots (`artifacts/datasets/<name>.csv`)
 * - 20 950ms  dashboard_sample_data checks two charts (done at 21 050ms)
 * - 21 080ms  dashboard_screenshot renders all nine tiles (done at 21 180ms)
 *
 * The harness keeps the real file viewer for dashboard files, so the
 * DashboardRenderer runs for real inside the artifacts panel.
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

test.describe("dashboard artifact (fixture harness)", () => {
  test("the linked dashboard renders a chip that opens the panel on the dashboard", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    const chip = page.locator('[data-testid="chat-md-file-chip"][data-kind="dashboard"]');
    await expect(chip).toHaveCount(1);
    await expect(chip).toContainText("revenue.dashboard.json");
    await expect(chip).toContainText("Open");
    await expect(chip).toHaveAttribute("data-action", "open");
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
    await chip.click();
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await expect(page.getByTestId("artifacts-tab-files")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByTestId("artifacts-file-view")).toHaveAttribute(
      "data-file-id",
      "file-fixture-dashboard",
    );
  });

  test("the panel scrolls the dashboard when it is taller than the panel", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1600, height: 900 });
    await page.goto(at(24_800));
    await waitForHydration(page);
    await page.locator('[data-testid="chat-md-file-chip"][data-kind="dashboard"]').click();
    await expect(page.getByTestId("chat-dashboard-view")).toHaveAttribute("data-pending", "0");
    const view = page.getByTestId("artifacts-file-view");
    const overflow = await view.evaluate((el) => el.scrollHeight - el.clientHeight);
    expect(overflow).toBeGreaterThan(200);
    await view.hover();
    await page.mouse.wheel(0, 600);
    await expect.poll(() => view.evaluate((el) => el.scrollTop)).toBeGreaterThan(300);
  });

  test("the panel renders the dashboard with nine tiles and live charts", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    await page.locator('[data-testid="chat-md-file-chip"][data-kind="dashboard"]').click();
    const view = page.getByTestId("chat-dashboard-view");
    await expect(view).toBeVisible();
    await expect(view).toHaveAttribute("data-pending", "0");
    const renderer = view.locator("[data-dashboard-renderer]");
    await expect(renderer).toBeVisible();
    await expect(renderer.locator("h2")).toHaveText("Revenue overview 2024");
    await expect(renderer.locator("[data-chart-id]")).toHaveCount(9);
    // No tile failed: every dataset resolved and parsed.
    await expect(renderer.locator("[data-dashboard-tile-error]")).toHaveCount(0);
    // ECharts drew the line chart with the SVG renderer.
    const line = renderer.locator('[data-chart-id="revenue_trend"]');
    await expect(line).toHaveAttribute("data-chart-type", "line");
    await expect(line.locator("svg").first()).toBeVisible();
    // The KPI tile formatted its value as currency.
    await expect(renderer.locator('[data-chart-id="kpi_revenue"]')).toContainText("$");
  });

  test("changing the region filter narrows the table and the charts", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    await page.locator('[data-testid="chat-md-file-chip"][data-kind="dashboard"]').click();
    const renderer = page.getByTestId("chat-dashboard-view").locator("[data-dashboard-renderer]");
    await expect(renderer.locator("[data-chart-id]")).toHaveCount(9);
    const table = renderer.locator('[data-chart-id="top_months"]');
    // Ten rows: the table sorts by revenue and limits to 10 of 48.
    await expect(table.locator("tbody tr")).toHaveCount(10);
    // The period filter is bound to the monthly dataset the table reads:
    // narrowing it to November onwards leaves 2 months x 4 regions.
    const filterBar = renderer.locator("[data-dashboard-filters]");
    await expect(filterBar).toBeVisible();
    await filterBar.getByLabel("Period from").fill("2024-11-01");
    await expect(table.locator("tbody tr")).toHaveCount(8);
    // The region filter is an `in` filter over the regional dataset: its
    // chips are pressed by default and toggle off on click.
    const west = filterBar.getByRole("button", { name: "West" });
    await expect(west).toHaveAttribute("aria-pressed", "true");
    await west.click();
    await expect(west).toHaveAttribute("aria-pressed", "false");
    // The pie tile still renders (three slices now) with no error band.
    await expect(renderer.locator('[data-chart-id="region_share"] svg').first()).toBeVisible();
    await expect(renderer.locator("[data-dashboard-tile-error]")).toHaveCount(0);
  });

  test("the expand action opens the dashboard in the overlay", async ({ page }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    await page.locator('[data-testid="chat-md-file-chip"][data-kind="dashboard"]').click();
    await page.getByTestId("chat-dashboard-expand").click();
    const lightbox = page.getByTestId("artifact-lightbox");
    await expect(lightbox).toBeVisible();
    await expect(lightbox).toContainText("Revenue overview 2024");
    await expect(lightbox.locator("[data-chart-id]")).toHaveCount(9);
    await page.keyboard.press("Escape");
    await expect(lightbox).not.toBeVisible();
  });

  test("the two dashboard tool cards summarize the check and the render", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    // The trailing chain has eight card kinds, more than the strip shows,
    // so the check and render chips sit behind "+2 more". Picking it opens
    // the group and expands the first hidden card (the data check); the
    // render card is then one compact chip away.
    const strip = page.getByTestId("chat-tool-chip-strip").last();
    await expect(strip.getByTestId("chat-tool-chip-more")).toHaveText("+2 more");
    await strip.getByTestId("chat-tool-chip-more").click();
    const frameOf = (kind: string) =>
      page.locator(`[data-testid="chat-tool-card"][data-kind="${kind}"]`);
    await expect(frameOf("dashboard_sample")).toHaveAttribute("data-density", "expanded");
    const sample = page.getByTestId("chat-dashboard-sample-card");
    await expect(sample).toBeVisible();
    await expect(sample.getByTestId("chat-dashboard-sample-chart")).toHaveCount(2);
    await expect(sample).toContainText("revenue_trend");
    await expect(sample.getByTestId("chat-data-table").first()).toBeVisible();
    await expect(frameOf("dashboard_screenshot")).toHaveAttribute("data-density", "compact");
    await frameOf("dashboard_screenshot").getByTestId("chat-tool-chip").click();
    await expect(frameOf("dashboard_screenshot")).toHaveAttribute("data-density", "expanded");
    const shot = page.getByTestId("chat-dashboard-screenshot-card");
    await expect(shot).toBeVisible();
    await expect(shot.getByTestId("chat-dashboard-screenshot-rendered")).toHaveCount(9);
    await expect(shot.getByTestId("chat-dashboard-screenshot-failed")).toHaveCount(0);
    await expect(shot.locator("img")).toHaveCount(0);
  });

  test("the load card names the version it pulled, the path and the dataset rows", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    const chips = page.getByTestId("chat-tool-chip");
    const chip = chips.filter({ hasText: "Loaded Revenue overview v3" }).first();
    await expect(chip).toBeVisible();
    await chip.click();
    const card = page.getByTestId("chat-dashboard-load-card");
    await expect(card).toBeVisible();
    await expect(card.getByTestId("chat-dashboard-load-name")).toHaveText("Revenue overview v3");
    await expect(card.getByTestId("chat-dashboard-load-path")).toHaveText(
      "artifacts/revenue.dashboard.json",
    );
    const rows = card.getByTestId("chat-dashboard-load-dataset");
    await expect(rows).toHaveCount(3);
    const monthly = card.locator(
      '[data-testid="chat-dashboard-load-dataset"][data-dataset="revenue_monthly"]',
    );
    await expect(monthly).toContainText("48");
    await expect(monthly).toContainText("artifacts/datasets/revenue_monthly.csv");
    await expect(card.getByTestId("chat-dashboard-load-error")).toHaveCount(0);
  });

  test("the dashboard file gets a timeline card labelled Dashboard", async ({ page }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    const card = page
      .getByTestId("chat-artifact-card")
      .filter({ hasText: "revenue.dashboard.json" });
    // Eleven files in the run: the dashboard may sit in the compact rows.
    const row = page
      .getByTestId("chat-artifact-card-row")
      .filter({ hasText: "revenue.dashboard.json" });
    const anyCard = (await card.count()) ? card : row;
    await expect(anyCard).toHaveCount(1);
    const primary = anyCard.getByTestId("chat-artifact-card-primary");
    await expect(primary).toHaveText("Open");
    await primary.click();
    await expect(page.getByTestId("artifacts-file-view")).toHaveAttribute(
      "data-file-id",
      "file-fixture-dashboard",
    );
  });
});

test.describe("publish from chat (fixture gallery)", () => {
  const openDashboard = async (page: import("@playwright/test").Page) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    await page.locator('[data-testid="chat-md-file-chip"][data-kind="dashboard"]').click();
    await expect(page.getByTestId("chat-dashboard-view")).toHaveAttribute("data-pending", "0");
  };

  test("the strip says which dashboard the file was loaded from, before any publish", async ({
    page,
  }) => {
    await openDashboard(page);
    // Nothing from this chat is in the fixture gallery yet, but the file
    // stem (`revenue`) is the slug of the dashboard the agent loaded.
    await expect(page.getByTestId("chat-dashboard-published")).toHaveCount(0);
    const strip = page.getByTestId("chat-dashboard-loaded");
    await expect(strip).toBeVisible();
    await expect(strip).toHaveAttribute("data-dashboard-slug", "revenue");
    await expect(strip).toContainText("Loaded from Revenue overview");
    await expect(strip).toContainText("(v3)");
    await expect(strip.getByTestId("chat-dashboard-loaded-open")).toHaveAttribute(
      "href",
      "/dashboards/revenue",
    );
    // The strip's action opens the dialog on that dashboard.
    await strip.getByTestId("chat-dashboard-publish-version").click();
    const dialog = page.getByTestId("chat-dashboard-publish-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByTestId("chat-dashboard-publish-target")).toHaveValue(
      "dash_fixture_existing",
    );
    await expect(dialog.getByTestId("chat-dashboard-publish-submit")).toHaveText(
      /Publish version/,
    );
  });

  test("Publish sits next to Expand and opens the dialog on the loaded dashboard", async ({
    page,
  }) => {
    await openDashboard(page);
    const header = page.getByTestId("chat-dashboard-expand").locator("..");
    const publish = header.getByTestId("chat-dashboard-publish");
    await expect(publish).toBeVisible();
    await expect(page.getByTestId("chat-dashboard-loaded")).toBeVisible();
    await publish.click();
    const dialog = page.getByTestId("chat-dashboard-publish-dialog");
    await expect(dialog).toBeVisible();
    // The fixture gallery's editable dashboard is the preselected target,
    // and the form adopts its settings.
    const target = dialog.getByTestId("chat-dashboard-publish-target");
    await expect(target.locator("option")).toHaveText(["New dashboard", "Revenue overview"]);
    await expect(target).toHaveValue("dash_fixture_existing");
    await expect(dialog).toContainText("Publish a new version");
    await expect(dialog.getByTestId("chat-dashboard-publish-name")).toHaveValue("Revenue overview");
    await expect(dialog.getByTestId("chat-dashboard-publish-description")).toHaveValue(
      /^Monthly revenue by region/,
    );
    await expect(dialog.getByTestId("chat-dashboard-publish-interval")).toHaveValue("1440");
    await expect(dialog.getByTestId("chat-dashboard-publish-anchor")).toHaveValue("06:00");
    await expect(dialog.getByTestId("chat-dashboard-publish-timezone")).toHaveValue(
      "America/New_York",
    );
    // A fresh publish is one select away.
    await target.selectOption("new");
    await expect(dialog).toContainText("Publish to the dashboards gallery");
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
  });

  test("the dataset table shows each SQL dataset's connection and found snapshot", async ({
    page,
  }) => {
    await openDashboard(page);
    await page.getByTestId("chat-dashboard-publish").click();
    const rows = page.getByTestId("chat-dashboard-publish-dataset");
    await expect(rows).toHaveCount(3);
    for (const name of ["summary", "revenue_monthly", "revenue_by_region"]) {
      const row = page.locator(
        `[data-testid="chat-dashboard-publish-dataset"][data-dataset="${name}"]`,
      );
      await expect(row).toContainText("SQL · warehouse");
      await expect(row).toHaveAttribute("data-status", "found");
      await expect(row).toContainText(`Found artifacts/datasets/${name}.csv`);
    }
    await expect(page.getByTestId("chat-dashboard-publish-error")).toHaveCount(0);
    await expect(page.getByTestId("chat-dashboard-publish-submit")).toBeEnabled();
  });

  test("submitting shows the published strip with a link to the dashboard", async ({
    page,
  }) => {
    await openDashboard(page);
    await page.getByTestId("chat-dashboard-publish").click();
    const dialog = page.getByTestId("chat-dashboard-publish-dialog");
    // Publish a fresh dashboard rather than a version of the loaded one.
    await dialog.getByTestId("chat-dashboard-publish-target").selectOption("new");
    await dialog.getByTestId("chat-dashboard-publish-name").fill("Revenue overview (team)");
    await dialog.getByTestId("chat-dashboard-publish-submit").click();
    await expect(dialog).not.toBeVisible();
    const strip = page.getByTestId("chat-dashboard-published");
    await expect(strip).toBeVisible();
    // The publish from this file replaces the "Loaded from" strip.
    await expect(page.getByTestId("chat-dashboard-loaded")).toHaveCount(0);
    await expect(strip).toContainText("Published as Revenue overview (team)");
    await expect(strip).toContainText("v1");
    await expect(strip.getByTestId("chat-dashboard-published-open")).toHaveAttribute(
      "href",
      "/dashboards/revenue-overview-2024",
    );
    // A second publish targets the dashboard just created.
    await strip.getByTestId("chat-dashboard-publish-version").click();
    await expect(dialog).toBeVisible();
    await expect(dialog.getByTestId("chat-dashboard-publish-target")).toHaveValue(
      "dash_fixture_published",
    );
    await expect(dialog.getByTestId("chat-dashboard-publish-submit")).toHaveText(
      /Publish version/,
    );
    await dialog.getByTestId("chat-dashboard-publish-submit").click();
    await expect(strip).toContainText("v2");
  });
});
