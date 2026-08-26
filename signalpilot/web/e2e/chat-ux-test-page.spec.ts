import { expect, test } from "@playwright/test";

/**
 * Exercises the fixture-driven chat UX harness at /chats/test. The replay is
 * frozen at deterministic offsets via ?at=<ms>&paused=1, so no model,
 * gateway, or warehouse is required.
 */

const BASE = process.env.SP_WEB_BASE_URL ?? "http://localhost:3200";
const at = (ms: number) => `${BASE}/chats/test?at=${ms}&paused=1`;

test.describe("chat UX test harness", () => {
  test("shows a live working header while the first chain streams", async ({
    page,
  }) => {
    await page.goto(at(2_000));
    const group = page.getByTestId("chat-activity-group").first();
    await expect(group).toBeVisible();
    await expect(group).toContainText("Get table schema");
    // Source chips from the schema tool input.
    await expect(group).toContainText("fct_orders");
  });

  test("renders a failed SQL step with formatted SQL and the error detail", async ({
    page,
  }) => {
    await page.goto(at(6_000));
    const group = page.getByTestId("chat-activity-group").first();
    await expect(group).toContainText("Validated SQL");
    await expect(group).toContainText("does not exist");
    // sql-formatter upper-cases keywords in the SQL card.
    await expect(group).toContainText("SELECT");
    // The follow-up warehouse query is still running.
    await expect(group).toContainText("Queried the warehouse");
  });

  test("mid-run narration splits the run into separate activity groups", async ({
    page,
  }) => {
    await page.goto(at(13_000));
    const groups = page.getByTestId("chat-activity-group");
    await expect(groups).toHaveCount(2);
    // The first chain has collapsed to a summary line.
    await expect(groups.first()).toContainText("Worked through 5 steps");
    // The streamed narration sits between the two chains.
    await expect(
      page.getByText("growth stories differ sharply by region"),
    ).toBeVisible();
    // The second chain is live with rich cards.
    await expect(groups.nth(1)).toContainText("Generated a file");
    await expect(groups.nth(1)).toContainText("analysis/q3_growth.py");
    await expect(groups.nth(1)).toContainText("Ran Python calculation");
    await expect(groups.nth(1)).toContainText('q3 = {"EMEA"');
  });

  test("collapses both chains to summaries and shows artifacts when complete", async ({
    page,
  }) => {
    await page.goto(at(21_200));
    const groups = page.getByTestId("chat-activity-group");
    await expect(groups).toHaveCount(2);
    await expect(groups.first()).toContainText(
      "Worked through 5 steps · 2 queries · 1 error",
    );
    await expect(groups.nth(1)).toContainText(
      "Worked through 8 steps · 2 code runs · 4 files",
    );
    await expect(page.getByText("EMEA drove the growth")).toBeVisible();
    await expect(
      page.getByText("q3_revenue_by_region.csv").first(),
    ).toBeVisible();
    await expect(page.getByTestId("standalone-chart-artifact")).toBeVisible();
    // A collapsed chain reopens on demand.
    await groups.nth(1).locator("button").first().click();
    await expect(groups.nth(1)).toContainText("Published a chart");
  });

  test("expands charts and reports in a fullscreen viewer", async ({
    page,
  }) => {
    await page.goto(at(21_200));
    const expandButtons = page.getByTestId("artifact-expand");
    // One for the Vega chart, one for the HTML report.
    await expect(expandButtons).toHaveCount(2);
    await expandButtons.first().click();
    const lightbox = page.getByTestId("artifact-lightbox");
    await expect(lightbox).toBeVisible();
    await expect(lightbox).toContainText("q3_growth_by_region.vl.json");
    await page.keyboard.press("Escape");
    await expect(lightbox).not.toBeVisible();
    await expandButtons.nth(1).click();
    await expect(lightbox).toBeVisible();
    await expect(
      lightbox.locator("iframe[title*='q3_regional_review']"),
    ).toBeVisible();
    await page.getByLabel("Close viewer").click();
    await expect(lightbox).not.toBeVisible();
  });

  test("replay controls scrub the run deterministically", async ({ page }) => {
    await page.goto(at(0));
    await expect(page.getByTestId("chat-test-scrub")).toBeVisible();
    await page.getByTestId("chat-test-skip").click();
    await expect(
      page.getByTestId("chat-activity-group").first(),
    ).toContainText("Worked through 5 steps");
    await page.getByTestId("chat-test-restart").click();
    await expect(
      page.getByTestId("chat-activity-group").first(),
    ).not.toContainText("Worked through");
  });
});
