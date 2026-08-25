import { expect, test } from "@playwright/test";

/**
 * Exercises the fixture-driven chat UX harness at /chats/test. The replay is
 * frozen at deterministic offsets via ?at=<ms>&paused=1, so no model,
 * gateway, or warehouse is required.
 */

const BASE = process.env.SP_WEB_BASE_URL ?? "http://localhost:3200";
const at = (ms: number) => `${BASE}/chats/test?at=${ms}&paused=1`;

test.describe("chat UX test harness", () => {
  test("shows a live working header while the run streams", async ({
    page,
  }) => {
    await page.goto(at(2_000));
    const activity = page.getByTestId("chat-live-activity");
    await expect(activity).toBeVisible();
    await expect(activity).toContainText("Get table schema");
    // Source chips from the schema tool input.
    await expect(activity).toContainText("fct_orders");
  });

  test("renders a failed SQL step with formatted SQL and the error detail", async ({
    page,
  }) => {
    await page.goto(at(6_000));
    const activity = page.getByTestId("chat-live-activity");
    await expect(activity).toContainText("Validated SQL");
    await expect(activity).toContainText("does not exist");
    // sql-formatter upper-cases keywords in the SQL card.
    await expect(activity).toContainText("SELECT");
    // The follow-up warehouse query is still running.
    await expect(activity).toContainText("Queried the warehouse");
  });

  test("shows generated files and executed python as rich cards", async ({
    page,
  }) => {
    await page.goto(at(13_000));
    const activity = page.getByTestId("chat-live-activity");
    await expect(activity).toContainText("Generated a file");
    await expect(activity).toContainText("analysis/q3_growth.py");
    await expect(activity).toContainText("Ran a command");
    await expect(activity).toContainText("Ran Python calculation");
    await expect(activity).toContainText('q3 = {"EMEA"');
  });

  test("collapses to a work summary and shows artifacts when complete", async ({
    page,
  }) => {
    await page.goto(at(21_200));
    const activity = page.getByTestId("chat-live-activity");
    await expect(activity).toContainText("Worked through 13 steps");
    await expect(activity).toContainText("1 error");
    await expect(page.getByText("EMEA drove the growth")).toBeVisible();
    await expect(
      page.getByText("q3_revenue_by_region.csv").first(),
    ).toBeVisible();
    await expect(
      page.getByTestId("standalone-chart-artifact"),
    ).toBeVisible();
    // The collapsed timeline reopens on demand.
    await activity.locator("button").first().click();
    await expect(activity).toContainText("Updated the plan");
    await expect(activity).toContainText("Published a chart");
  });

  test("replay controls scrub the run deterministically", async ({ page }) => {
    await page.goto(at(0));
    await expect(page.getByTestId("chat-test-scrub")).toBeVisible();
    await page.getByTestId("chat-test-skip").click();
    await expect(page.getByTestId("chat-live-activity")).toContainText(
      "Worked through 13 steps",
    );
    await page.getByTestId("chat-test-restart").click();
    await expect(page.getByTestId("chat-live-activity")).not.toContainText(
      "Worked through",
    );
  });
});
