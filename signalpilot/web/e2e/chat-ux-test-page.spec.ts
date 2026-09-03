import { expect, test } from "@playwright/test";

/**
 * Exercises the fixture-driven chat UX harness at /chats/test. The replay is
 * frozen at deterministic offsets via ?at=<ms>&paused=1, so no model,
 * gateway, or warehouse is required.
 *
 * The fixture timeline has three activity groups: the schema / SQL chain
 * (9 steps, one failed validation), the code-and-notebook chain (10 steps,
 * 6 files) after the mid-run narration, and a short discovery chain at
 * 21.2–24 s (list_tables, explore_columns, dbt run, knowledge search and a
 * connector tool) that exercises the remaining tool cards.
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
    // The agent's one-line `description` titles the query card.
    await expect(group).toContainText(
      "Comparing Q2 and Q3 revenue by region from fct_orders",
    );
  });

  test("mid-run narration splits the run into separate activity groups", async ({
    page,
  }) => {
    await page.goto(at(13_000));
    const groups = page.getByTestId("chat-activity-group");
    await expect(groups).toHaveCount(2);
    // The first chain has collapsed to a summary line.
    await expect(groups.first()).toContainText("Worked through 9 steps");
    // The streamed narration sits between the two chains.
    await expect(
      page.getByText("growth stories differ sharply by region"),
    ).toBeVisible();
    // The second chain is live with rich cards.
    await expect(groups.nth(1)).toContainText("Generated a file");
    await expect(groups.nth(1)).toContainText("analysis/q3_growth.py");
    await expect(groups.nth(1)).toContainText("Ran a command");
    await expect(groups.nth(1)).toContainText(
      "python analysis/q3_growth.py --check",
    );
  });

  test("collapses all chains to summaries and shows the inline figure when complete", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    const groups = page.getByTestId("chat-activity-group");
    await expect(groups).toHaveCount(3);
    await expect(groups.first()).toContainText(
      "Worked through 9 steps · 2 queries · 1 error",
    );
    await expect(groups.nth(1)).toContainText(
      "Worked through 10 steps · 2 code runs · 6 files",
    );
    // The trailing discovery chain folds to a plain count with one chip per
    // card kind (table list, column profile, dbt run, knowledge, connector).
    await expect(groups.nth(2)).toContainText("Worked through 5 steps");
    await expect(groups.nth(2)).toContainText("dbt run");
    await expect(groups.nth(2)).toContainText("47 tables");
    await expect(
      groups.nth(2).locator('[data-testid="chat-tool-chip"][data-kind="dbt_run"]').first(),
    ).toBeVisible();
    await expect(page.getByText("EMEA drove the growth")).toBeVisible();
    // The chart the notebook cell saved renders inline from the manifest.
    await expect(page.getByTestId("chat-md-figure")).toBeVisible();
    // The chart the run never saved is a block "not available" band.
    await expect(page.getByTestId("chat-md-image-missing")).toBeVisible();
    // The collapsed code chain keeps its files visible in a footer.
    await expect(
      groups.nth(1).getByTestId("chat-group-artifact-cards"),
    ).toContainText("q3_revenue_by_region.csv");
    // A collapsed chain reopens on demand, and its cards move under the
    // steps that produced them.
    await groups.nth(1).locator("button").first().click();
    await expect(groups.nth(1)).toContainText("Executed notebook cells");
    await expect(
      groups.nth(1).getByTestId("chat-group-artifact-cards"),
    ).toHaveCount(0);
    await expect(
      groups.nth(1).getByTestId("chat-step-artifact-cards"),
    ).toHaveCount(6);
  });

  test("shows the agent plan as an always-visible card in the main window", async ({
    page,
  }) => {
    // First TodoWrite has landed: 0/4, first item live, list expanded.
    await page.goto(at(2_000));
    await waitForHydration(page);
    const tracker = page.getByTestId("chat-plan-tracker");
    await expect(tracker).toBeVisible();
    await expect(tracker).toContainText("0/4");
    await expect(tracker).toContainText(
      "Confirm the revenue model and region join",
    );
    await expect(tracker).toContainText("Save the chart and the underlying rows");
    // The header toggle collapses the checklist to the one-line summary.
    const header = tracker.locator("button").first();
    await expect(header).toHaveAttribute("aria-expanded", "true");
    await header.click();
    await expect(header).toHaveAttribute("aria-expanded", "false");
    // Late in the run the second TodoWrite advances the plan to 3/4.
    await page.goto(at(16_000));
    await expect(tracker).toContainText("3/4");
    // After the run completes the plan stays in the transcript, folded.
    await page.goto(at(30_000));
    await expect(tracker).toBeVisible();
    await expect(tracker).toContainText("3/4");
    await expect(tracker.locator("button").first()).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  test("replay controls scrub the run deterministically", async ({ page }) => {
    await page.goto(at(0));
    await waitForHydration(page);
    await expect(page.getByTestId("chat-test-scrub")).toBeVisible();
    await page.getByTestId("chat-test-skip").click();
    await expect(
      page.getByTestId("chat-activity-group").first(),
    ).toContainText("Worked through 9 steps");
    await page.getByTestId("chat-test-restart").click();
    await expect(
      page.getByTestId("chat-activity-group").first(),
    ).not.toContainText("Worked through");
  });
});
