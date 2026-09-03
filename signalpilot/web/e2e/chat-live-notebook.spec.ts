import { expect, test } from "@playwright/test";

/**
 * Notebook panel on the standalone chat surface, exercised through the
 * fixture harness at /chats/test (no model, gateway, or warehouse needed).
 *
 * The harness simulates the gateway's conversation notebook resource from
 * the fixture events (lib/chat-test-fixture.ts):
 * -  8 720ms  notebook_started → resource goes live, panel auto-opens
 * - 20 900ms  kernel_stopped → resource ends with a saved document
 *
 * The harness stubs the inline notebook view; resource selection logic is
 * covered by lib/chat-live-notebook.test.ts.
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

test.describe("live notebook panel (fixture harness)", () => {
  test("absent before the agent starts a notebook", async ({ page }) => {
    await page.goto(at(5_000));
    // The run is mid-flight but no notebook_started yet: no panel, no toggle.
    await expect(page.getByTestId("chat-activity-group").first()).toBeVisible();
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
    await expect(page.getByTestId("live-notebook-toggle")).toHaveCount(0);
  });

  test("auto-opens live once the notebook starts", async ({ page }) => {
    await page.goto(at(9_000));
    await waitForHydration(page);
    const panel = page.getByTestId("live-notebook-panel");
    await expect(panel).toBeVisible();
    await expect(page.getByTestId("live-notebook-status-live")).toBeVisible();
    // The live notebook mounts INLINE — no iframe anywhere in the panel.
    await expect(page.getByTestId("live-notebook-inline")).toBeVisible();
    await expect(page.getByTestId("chat-notebook-stub")).toBeVisible();
    await expect(
      page.getByTestId("live-notebook-panel").locator("iframe"),
    ).toHaveCount(0);
    // A pop-out affordance exists while live.
    await expect(page.getByTestId("live-notebook-popout")).toBeVisible();
  });

  test("close hides the panel and leaves a reopen toggle", async ({ page }) => {
    await page.goto(at(9_000));
    await waitForHydration(page);
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await page.getByTestId("live-notebook-close").click();
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
    const toggle = page.getByTestId("live-notebook-toggle");
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await expect(page.getByTestId("live-notebook-status-live")).toBeVisible();
  });

  test("keeps the rendered notebook after the run ends (sticky attach)", async ({
    page,
  }) => {
    // Enter mid-notebook (panel auto-opens live), then play to the end.
    await page.goto(at(9_000));
    await waitForHydration(page);
    await expect(page.getByTestId("live-notebook-status-live")).toBeVisible();
    await page.getByTestId("chat-test-skip").click();
    // kernel_stopped ends the resource, but the panel keeps rendering the
    // notebook from its saved document. No HTML archive iframe, ever.
    const panel = page.getByTestId("live-notebook-panel");
    await expect(panel).toBeVisible();
    await expect(
      page.getByTestId("live-notebook-status-finished"),
    ).toBeVisible();
    await expect(page.getByTestId("live-notebook-inline")).toBeVisible();
    await expect(page.getByTestId("chat-notebook-stub")).toBeVisible();
    await expect(page.getByTestId("archived-notebook-frame")).toHaveCount(0);
  });

  test("a finished run deep-link keeps the panel closed but reachable", async ({
    page,
  }) => {
    await page.goto(at(24_800));
    await waitForHydration(page);
    // The link is not live on arrival, so nothing auto-opens...
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
    // ...but the toggle reopens straight into the real notebook view,
    // rendered document-first with no kernel (never the HTML archive).
    const toggle = page.getByTestId("live-notebook-toggle");
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await expect(
      page.getByTestId("live-notebook-status-finished"),
    ).toBeVisible();
    await expect(page.getByTestId("live-notebook-inline")).toBeVisible();
    await expect(page.getByTestId("chat-notebook-stub")).toBeVisible();
    await expect(page.getByTestId("archived-notebook-frame")).toHaveCount(0);
  });

  test("restarting the replay resets and re-triggers the auto-open", async ({
    page,
  }) => {
    await page.goto(at(9_000));
    await waitForHydration(page);
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await page.getByTestId("live-notebook-close").click();
    await page.getByTestId("chat-test-restart").click();
    // Back before notebook_started: no panel, no toggle.
    await expect(page.getByTestId("live-notebook-toggle")).toHaveCount(0);
    // The replay runs forward; the panel auto-opens again at ~8.7s.
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("live-notebook-status-live")).toBeVisible();
  });
});

test.describe("chat notebook pop-out route", () => {
  test("renders a clear message when the conversation param is missing", async ({
    page,
  }) => {
    await page.goto(`${BASE}/chat-notebook`);
    await expect(
      page.getByTestId("chat-notebook-missing-params"),
    ).toBeVisible();
  });

  test("fetches the notebook resource when a conversation is given", async ({
    page,
  }) => {
    // No gateway runs in this suite, so the resource fetch cannot resolve.
    // The route must still mount and wait on the resource instead of
    // reporting a bad link. Generous timeout: in dev the route compiles on
    // its first hit.
    await page.goto(`${BASE}/chat-notebook?conversation=conv-e2e-1`);
    await expect(
      page.getByTestId("chat-notebook-missing-params"),
    ).toHaveCount(0, { timeout: 30_000 });
  });
});
