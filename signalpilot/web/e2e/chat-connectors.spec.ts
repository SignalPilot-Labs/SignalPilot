import { expect, test, type Page } from "@playwright/test";

/**
 * Chat-side connector surfaces on the fixture harness at /chats/test:
 * the gear opens the right-side "Chat settings" panel with fixture
 * connectors, "On for me" toggles, and the in-chat sign-in card that a
 * proxy sign-in error produces (?signin=1).
 */

const BASE = process.env.SP_WEB_BASE_URL ?? "http://localhost:3200";
const at = (ms: number, extra = "") => `${BASE}/chats/test?at=${ms}&paused=1${extra}`;

/** Next dev can keep a hidden prerendered copy of the page outside <main>;
 * scoping to the live region keeps every locator unambiguous. */
const main = (page: Page) => page.locator("main");

async function waitForHydration(page: Page) {
  await expect(main(page).getByTestId("chat-test-harness")).toHaveAttribute("data-hydrated", "1");
}

test.describe("chat settings panel (fixture harness)", () => {
  test("the gear opens a right-side panel titled Chat settings with connector rows", async ({ page }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    await expect(main(page).getByTestId("chat-settings-panel")).toHaveCount(0);
    const gear = main(page).getByTestId("chat-settings-gear");
    await expect(gear).toHaveAttribute("aria-expanded", "false");
    await gear.click();
    const panel = main(page).getByTestId("chat-settings-panel");
    await expect(panel).toBeVisible();
    await expect(gear).toHaveAttribute("aria-expanded", "true");
    await expect(panel).toContainText("Chat settings");
    const model = panel.getByTestId("chat-settings-model-select");
    await expect(model).toHaveValue("claude-opus-5");
    await expect(model.locator("option")).toHaveText([
      "Opus 4.6",
      "Sonnet 4.6",
      "Opus 5",
      "Fable 5.1",
    ]);
    await model.selectOption("claude-fable-5-1");
    await expect(model).toHaveValue("claude-fable-5-1");
    await expect(panel).toContainText("Available in all your chats");
    await expect(panel.getByTestId("chat-settings-connector-row")).toHaveCount(5);
    await expect(panel.getByTestId("chat-settings-manage")).toHaveAttribute("href", /\/settings\/connectors/);
    // The panel says what the next chat gets, and each row carries its tool count and a deep link.
    await expect(panel.getByTestId("chat-settings-summary")).toHaveText("3 connectors · 17 tools go to your next chat");
    const jira = panel.getByTestId("chat-settings-connector-row").filter({ hasText: "Jira" });
    await expect(jira.getByTestId("chat-settings-row-tools")).toHaveText("10 tools · 5 on");
    await expect(jira.getByTestId("chat-settings-connector-link")).toHaveAttribute("href", /\/settings\/connectors\?fixture=1&open=con_jira/);
    await expect(jira).toContainText("Organization");
    // It sits in the right-hand slot, not in a popover over the composer.
    const panelBox = await panel.boundingBox();
    const viewport = page.viewportSize();
    expect((panelBox?.x ?? 0) + (panelBox?.width ?? 0)).toBeGreaterThan((viewport?.width ?? 0) - 40);
    await panel.getByTestId("chat-settings-close").click();
    await expect(main(page).getByTestId("chat-settings-panel")).toHaveCount(0);
  });

  test("On for me toggles a connector for the member", async ({ page }) => {
    await page.goto(at(24_800, "&settings=1"));
    await waitForHydration(page);
    const row = main(page).getByTestId("chat-settings-connector-row").filter({ hasText: "Snowflake docs" });
    const toggle = row.getByTestId("chat-settings-on-for-me");
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await expect(row.getByTestId("connector-status-pill")).toHaveText("Off");
    // Toasts mount outside <main>.
    await expect(page.getByText("Snowflake docs is off for you · applies to new chats")).toBeVisible();
  });

  test("rows that need a fix show the fix, not a green switch", async ({ page }) => {
    await page.goto(at(24_800, "&settings=1"));
    await waitForHydration(page);
    const linear = main(page).getByTestId("chat-settings-connector-row").filter({ hasText: "Linear" });
    await expect(linear.getByTestId("connector-status-pill")).toHaveText("Unreachable");
    await expect(linear.getByTestId("chat-settings-retry")).toBeVisible();
    await expect(linear.getByTestId("chat-settings-on-for-me")).toHaveCount(0);
    const slack = main(page).getByTestId("chat-settings-connector-row").filter({ hasText: "Slack" });
    await expect(slack.getByTestId("connector-status-pill")).toHaveText("Tools changed");
    await expect(slack.getByTestId("chat-settings-review")).toHaveAttribute("href", /open=con_slack/);
    await expect(slack.getByTestId("chat-settings-on-for-me")).toHaveCount(0);
    const jira = main(page).getByTestId("chat-settings-connector-row").filter({ hasText: "Jira" });
    await expect(jira.getByTestId("chat-settings-on-for-me")).toBeVisible();
  });

  test("opening settings tucks the artifacts panel away and restores it on close", async ({ page }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    await main(page).getByTestId("live-notebook-toggle").click();
    await expect(main(page).getByTestId("live-notebook-panel")).toBeVisible();
    await main(page).getByTestId("chat-settings-gear").click();
    await expect(main(page).getByTestId("live-notebook-panel")).toHaveCount(0);
    await expect(main(page).getByTestId("chat-settings-panel")).toBeVisible();
    await main(page).getByTestId("chat-settings-close").click();
    await expect(main(page).getByTestId("live-notebook-panel")).toBeVisible();
  });
});

test.describe("connector sign-in card (fixture harness)", () => {
  test("no card without a sign-in error", async ({ page }) => {
    await page.goto(at(6_000));
    await expect(main(page).getByTestId("chat-activity-group").first()).toBeVisible();
    await expect(main(page).getByTestId("connector-signin-card")).toHaveCount(0);
  });

  test("renders from the proxy's sign-in error and signs in from the card", async ({ page }) => {
    await page.goto(at(3_000, "&signin=1"));
    await expect(main(page).getByTestId("connector-signin-card")).toHaveCount(0);
    await page.goto(at(6_000, "&signin=1"));
    await waitForHydration(page);
    const card = main(page).getByTestId("connector-signin-card");
    await expect(card).toHaveCount(1);
    await expect(card).toContainText("Sign in to Jira to continue");
    await expect(card).toContainText("search_issues");
    // The card says it once: the tool row collapses to "needs sign-in" and the
    // agent-facing error text never appears in the transcript.
    const transcript = await main(page).getByTestId("standalone-chat-messages").innerText();
    expect(transcript).not.toMatch(/needs you to sign in again/);
    expect(transcript).toMatch(/needs sign-in/);
    await card.getByTestId("connector-signin-button").click();
    await expect(card).toContainText("Signed in to Jira");
    await expect(card.getByTestId("connector-signin-retry")).toBeVisible();
    // The panel reflects the fresh sign-in too.
    await main(page).getByTestId("chat-settings-gear").click();
    const jira = main(page).getByTestId("chat-settings-connector-row").filter({ hasText: "Jira" });
    await expect(jira.getByTestId("connector-status-pill")).toHaveText("Connected");
  });

  test("the card's settings shortcut opens the Chat settings panel", async ({ page }) => {
    await page.goto(at(6_000, "&signin=1"));
    await waitForHydration(page);
    await main(page).getByTestId("connector-signin-card").getByTestId("connector-signin-settings").click();
    await expect(main(page).getByTestId("chat-settings-panel")).toBeVisible();
  });
});
