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
    // The run is mid-flight but no notebook_started yet: no panel, no
    // toggle, no notice.
    await expect(page.getByTestId("chat-activity-group").first()).toBeVisible();
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
    await expect(page.getByTestId("live-notebook-toggle")).toHaveCount(0);
    await expect(page.getByTestId("artifact-notice")).toHaveCount(0);
  });

  test("raises a notice instead of opening the panel when the notebook starts", async ({
    page,
  }) => {
    await page.goto(at(9_000));
    await waitForHydration(page);
    // The panel stays closed: the transcript is not yanked narrower.
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
    await expect(page.getByTestId("live-notebook-toggle")).toBeVisible();
    const notice = page.getByTestId("artifact-notice");
    await expect(notice).toHaveCount(1);
    await expect(notice).toHaveAttribute("data-notice-kind", "notebook");
    await expect(notice).toContainText("The agent started a notebook");
    // "View" opens the panel on the live notebook and clears the notice.
    await notice.getByTestId("artifact-notice-view").click();
    const panel = page.getByTestId("live-notebook-panel");
    await expect(panel).toBeVisible();
    await expect(page.getByTestId("artifacts-tab-notebook")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByTestId("live-notebook-status-live")).toBeVisible();
    // The live notebook mounts INLINE — no iframe anywhere in the panel.
    await expect(page.getByTestId("live-notebook-inline")).toBeVisible();
    await expect(page.getByTestId("chat-notebook-stub")).toBeVisible();
    await expect(panel.locator("iframe")).toHaveCount(0);
    // A pop-out affordance exists while live.
    await expect(page.getByTestId("live-notebook-popout")).toBeVisible();
    await expect(page.getByTestId("artifact-notice")).toHaveCount(0);
  });

  test("a dismissed notice leaves the reopen toggle", async ({ page }) => {
    await page.goto(at(9_000));
    await waitForHydration(page);
    const notice = page.getByTestId("artifact-notice");
    await expect(notice).toHaveCount(1);
    await notice.getByTestId("artifact-notice-dismiss").click();
    await expect(page.getByTestId("artifact-notice")).toHaveCount(0);
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
    const toggle = page.getByTestId("live-notebook-toggle");
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await expect(page.getByTestId("live-notebook-status-live")).toBeVisible();
  });

  test("charts and dashboards raise their own notices while the panel is closed", async ({
    page,
  }) => {
    // Enter just after the notebook started, then play: the SVG chart
    // lands at ~13.6s, the PNG at ~20.6s and the dashboard at ~20.75s.
    await page.goto(at(9_000));
    await waitForHydration(page);
    await expect(page.getByTestId("artifact-notice")).toHaveCount(1);
    await page.getByTestId("chat-test-skip").click();
    const notices = page.getByTestId("artifact-notice");
    // The stack keeps the newest three: the chart, the PNG and the
    // dashboard; the notebook notice was pushed out.
    await expect(notices).toHaveCount(3, { timeout: 15_000 });
    await expect(notices.nth(0)).toHaveAttribute("data-notice-kind", "chart");
    await expect(notices.nth(1)).toHaveAttribute("data-notice-kind", "chart");
    await expect(notices.nth(2)).toHaveAttribute(
      "data-notice-kind",
      "dashboard",
    );
    await expect(notices.nth(2)).toContainText("The agent started a dashboard");
    // Never opened by itself.
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
    // "View" on the dashboard notice opens the Files tab on that file.
    await notices.nth(2).getByTestId("artifact-notice-view").click();
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await expect(page.getByTestId("artifacts-tab-files")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByTestId("chat-dashboard-view")).toBeVisible();
    await expect(page.getByTestId("artifact-notice")).toHaveCount(0);
  });

  test("an open panel suppresses notices for artifacts that land", async ({
    page,
  }) => {
    await page.goto(at(9_000));
    await waitForHydration(page);
    await page.getByTestId("artifact-notice-view").click();
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await page.getByTestId("chat-test-skip").click();
    // The files landed (the Files tab counts them) but nothing nagged.
    await expect(page.getByTestId("artifacts-tab-files")).toContainText("11");
    await expect(page.getByTestId("artifact-notice")).toHaveCount(0);
  });

  test("keeps the rendered notebook after the run ends (sticky attach)", async ({
    page,
  }) => {
    // Enter mid-notebook, open the panel from the notice, then play to
    // the end.
    await page.goto(at(9_000));
    await waitForHydration(page);
    await page.getByTestId("artifact-notice-view").click();
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
    // The link is not live on arrival, so no panel and no notebook notice...
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
    await expect(
      page
        .getByTestId("artifact-notice")
        .and(page.locator("[data-notice-kind=notebook]")),
    ).toHaveCount(0);
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

  test("restarting the replay resets and re-raises the notebook notice", async ({
    page,
  }) => {
    await page.goto(at(9_000));
    await waitForHydration(page);
    await page.getByTestId("artifact-notice-view").click();
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await page.getByTestId("chat-test-restart").click();
    // Back before notebook_started: no panel, no toggle, no notice.
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
    await expect(page.getByTestId("live-notebook-toggle")).toHaveCount(0);
    await expect(page.getByTestId("artifact-notice")).toHaveCount(0);
    // The replay runs forward; the notice returns at ~8.7s and the panel
    // stays closed.
    await expect(page.getByTestId("artifact-notice")).toHaveAttribute(
      "data-notice-kind",
      "notebook",
      { timeout: 15_000 },
    );
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
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
