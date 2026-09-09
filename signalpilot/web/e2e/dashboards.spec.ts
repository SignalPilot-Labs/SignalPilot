import { expect, test, type Page } from "@playwright/test";

/**
 * Published dashboards: gallery, detail page, settings drawer, version and
 * refresh histories, exercised through the fixture
 * harness at /dashboards/test (in-memory API, no gateway).
 */

const BASE = process.env.SP_WEB_BASE_URL ?? "http://localhost:3200";
const harness = (query = "") => `${BASE}/dashboards/test${query}`;

/** Clicks before React hydration are silently lost — gate on the harness flag. */
async function waitForHydration(page: Page) {
  await expect(page.getByTestId("dashboards-test-harness")).toHaveAttribute("data-hydrated", "1");
}

test.describe("dashboards (fixture harness)", () => {
  test("the gallery shows the fixture card with its schedule", async ({ page }) => {
    await page.goto(harness(), { waitUntil: "load" });
    await waitForHydration(page);
    await expect(page.getByTestId("dashboard-publish-hint")).toContainText("How to publish");
    const card = page.locator('[data-testid="dashboard-card"][data-slug="revenue-overview-2024"]');
    await expect(card).toBeVisible();
    await expect(card).toContainText("Revenue overview 2024");
    await expect(card.getByTestId("dashboard-card-refresh")).toHaveText("Daily at 06:00 ET");
    await expect(card.getByTestId("dashboard-visibility-chip")).toHaveAttribute("data-visibility", "org");
    await expect(card.getByTestId("dashboard-status-dot")).toHaveAttribute("data-status", "succeeded");
    // The archived dashboard is hidden until the toggle is pressed.
    await expect(page.getByTestId("dashboard-card")).toHaveCount(1);
    await page.getByTestId("dashboard-gallery-archived-toggle").click();
    await expect(page.getByTestId("dashboard-card")).toHaveCount(2);
    await expect(page.locator('[data-testid="dashboard-card"][data-archived="1"]')).toContainText("Churn watch Q2");
  });

  test("the card links to the detail page, which renders nine tiles", async ({ page }) => {
    await page.goto(harness(), { waitUntil: "load" });
    await waitForHydration(page);
    await page.locator('[data-testid="dashboard-card"][data-slug="revenue-overview-2024"]').click();
    await expect(page.getByTestId("dashboard-page")).toHaveAttribute("data-slug", "revenue-overview-2024");
    await expect(page.getByTestId("dashboard-title")).toHaveText("Revenue overview 2024");
    await expect(page.getByTestId("dashboard-version-line")).toContainText("Version 3");
    await expect(page.getByTestId("dashboard-schedule-label")).toHaveText("Daily at 06:00 ET");
    const renderer = page.getByTestId("dashboard-canvas").locator("[data-dashboard-renderer]");
    await expect(renderer.locator("[data-chart-id]")).toHaveCount(10);
    await expect(renderer.locator("[data-dashboard-tile-error]")).toHaveCount(0);
    await expect(renderer.locator('[data-chart-id="kpi_revenue"]')).toContainText("$");
    await expect(renderer.locator('[data-chart-id="revenue_trend"] svg').first()).toBeVisible();
  });

  test("the settings drawer changes the interval and the header label follows", async ({ page }) => {
    await page.goto(harness("?view=detail"), { waitUntil: "load" });
    await waitForHydration(page);
    await expect(page.getByTestId("dashboard-schedule-label")).toHaveText("Daily at 06:00 ET");
    await page.getByTestId("dashboard-open-settings").click();
    const drawer = page.getByTestId("dashboard-settings-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByTestId("dashboard-settings-preview")).toContainText("Daily at 06:00 ET");
    await drawer.getByTestId("dashboard-settings-interval").selectOption("240");
    await expect(drawer.getByTestId("dashboard-settings-preview")).toContainText("Every 4 hours");
    await drawer.getByTestId("dashboard-settings-save").click();
    await expect(drawer).toHaveCount(0);
    await expect(page.getByTestId("dashboard-schedule-label")).toHaveText("Every 4 hours");
    await expect(page.getByTestId("toast")).toContainText("Settings saved");
  });

  test("the version list shows three versions with one current chip and Restore", async ({ page }) => {
    await page.goto(harness("?view=detail"), { waitUntil: "load" });
    await waitForHydration(page);
    const list = page.getByTestId("dashboard-version-list");
    await expect(list.getByTestId("dashboard-version-row")).toHaveCount(3);
    await expect(list.getByTestId("dashboard-version-current")).toHaveCount(1);
    await expect(list.locator('[data-testid="dashboard-version-row"][data-version-no="3"]')).toHaveAttribute(
      "data-current",
      "1",
    );
    await expect(list.getByTestId("dashboard-version-restore")).toHaveCount(2);
    // Restoring v1 creates v4 and moves the current chip to it.
    await list
      .locator('[data-testid="dashboard-version-row"][data-version-no="1"]')
      .getByTestId("dashboard-version-restore")
      .click();
    await expect(list.getByTestId("dashboard-version-row")).toHaveCount(4);
    await expect(list.locator('[data-testid="dashboard-version-row"][data-version-no="4"]')).toHaveAttribute(
      "data-current",
      "1",
    );
    await expect(page.getByTestId("dashboard-version-line")).toContainText("Version 4");
  });

  test("a version expands to its dataset files and downloads one", async ({ page }) => {
    await page.goto(harness("?view=detail"), { waitUntil: "load" });
    await waitForHydration(page);
    const row = page.locator('[data-testid="dashboard-version-row"][data-version-no="2"]');
    await expect(page.getByTestId("dashboard-version-datasets")).toHaveCount(0);
    await row.getByTestId("dashboard-version-toggle").click();
    await expect(row).toHaveAttribute("data-expanded", "1");
    const datasets = row.getByTestId("dashboard-version-dataset");
    await expect(datasets).toHaveCount(3);
    await expect(datasets.first()).toContainText("summary.csv");
    await expect(datasets.nth(1)).toContainText("revenue_monthly.csv");
    const downloadPromise = page.waitForEvent("download");
    await row
      .locator('[data-testid="dashboard-version-dataset"][data-dataset="revenue_by_region"]')
      .getByTestId("dashboard-version-dataset-download")
      .click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("revenue_by_region.csv");
    // The owner label is an email in the fixture, so it shows as is.
    await expect(page.getByTestId("dashboard-owner")).toHaveText("by daniel@example.com");
  });

  test("the refresh history exposes the failed row's error and the agent run link", async ({ page }) => {
    await page.goto(harness("?view=detail"), { waitUntil: "load" });
    await waitForHydration(page);
    const history = page.getByTestId("dashboard-refresh-history");
    await expect(history.getByTestId("dashboard-refresh-row")).toHaveCount(4);
    const failed = history.locator('[data-testid="dashboard-refresh-row"][data-status="failed"]');
    await expect(failed.getByTestId("dashboard-refresh-status")).toHaveText("Failed");
    await expect(failed.getByTestId("dashboard-refresh-error")).toHaveCount(0);
    await failed.getByTestId("dashboard-refresh-toggle-error").click();
    await expect(failed.getByTestId("dashboard-refresh-error")).toContainText("relation fct_orders does not exist");
    const running = history.locator('[data-testid="dashboard-refresh-row"][data-status="running"]');
    await expect(running.getByTestId("dashboard-refresh-chat-link")).toHaveAttribute(
      "href",
      "/chats/conv-fixture-agent-refresh",
    );
    // A running refresh disables Refresh now.
    await expect(page.getByTestId("dashboard-refresh-now")).toBeDisabled();
  });
});
