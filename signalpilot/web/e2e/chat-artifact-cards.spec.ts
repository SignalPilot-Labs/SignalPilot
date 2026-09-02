import { expect, test, type Page } from "@playwright/test";

/**
 * Inline artifact cards in the chat transcript, exercised through the
 * fixture harness at /chats/test (no model, gateway, or warehouse needed).
 *
 * Card timeline (lib/chat-test-fixture-data.ts + -artifact-files.ts):
 * -  9 200ms  Write analysis/q3_growth.py → first ready card (Script)
 * - 12 100ms  Write exports/q3_regional_review.html → PENDING card until
 * - 13 000ms  files_changed mirrors it → resolves to a ready Report card
 * - 13 050ms  Write exports/q3_growth_by_region.svg (mirrored 13 600ms)
 * - 13 700ms  Write exports/q3_revenue_by_region.csv (mirrored 14 050ms)
 * - 14 300ms  Edit q3_growth.py → its card gains the Updated badge
 * - 15 150ms  Write exports/q3_summary.md (mirrored 15 460ms) → 5th file
 * - 16 700ms  legacy TABLE preview (q3_revenue_by_region.csv) publishes →
 *             the CSV card is suppressed (the preview covers that file)
 * - 18 000ms  legacy REPORT preview (q3_regional_review.html) publishes →
 *             the HTML card is suppressed too
 * Collapse rule: compact rows appear only when ≥2 cards overflow the
 * 3-full-card budget (4 files → 4 full cards; 5 files → 3 + 2 rows).
 */

const BASE = process.env.SP_WEB_BASE_URL ?? "http://localhost:3200";
const at = (ms: number) => `${BASE}/chats/test?at=${ms}&paused=1`;

/** Clicks before React hydration are silently lost — gate on the harness flag. */
async function waitForHydration(page: Page) {
  await expect(page.getByTestId("chat-test-harness")).toHaveAttribute(
    "data-hydrated",
    "1",
  );
}

/** The harness stubs thumbnails via the chat UI context; downloads still go
 * through the authenticated fetch helper, so those need a network stub. */
async function stubFileContent(page: Page) {
  await page.route("**/api/chat/conversations/**/files/**/content*", (route) => {
    const url = route.request().url();
    const isImage = url.includes("file-fixture-chart");
    void route.fulfill({
      status: 200,
      contentType: isImage ? "image/svg+xml" : "text/csv",
      headers: { "access-control-allow-origin": "*" },
      body: isImage
        ? '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
        : "region,revenue\nAMER,1\n",
    });
  });
}

test.describe("inline artifact cards (fixture harness)", () => {
  test("no cards before the agent writes any file", async ({ page }) => {
    await page.goto(at(3_000));
    await expect(page.getByTestId("chat-activity-group").first()).toBeVisible();
    await expect(page.getByTestId("chat-artifact-cards")).toHaveCount(0);
  });

  test("the first written file renders one ready card with kind label and actions", async ({
    page,
  }) => {
    await page.goto(at(11_000));
    await waitForHydration(page);
    const cards = page.getByTestId("chat-artifact-card");
    await expect(cards).toHaveCount(1);
    await expect(cards).toContainText("q3_growth.py");
    await expect(cards).toContainText("Script");
    await expect(
      cards.getByTestId("chat-artifact-card-primary"),
    ).toHaveText("View");
    await expect(
      cards.getByTestId("chat-artifact-card-download"),
    ).toBeVisible();
    // No update has happened yet.
    await expect(page.getByTestId("chat-artifact-card-updated")).toHaveCount(0);
  });

  test("a write the mirror has not confirmed renders a pending card", async ({
    page,
  }) => {
    // 12.5s: the report Write landed at 12.1s; files_changed arrives at 13s.
    await page.goto(at(12_500));
    const pending = page.getByTestId("chat-artifact-card-pending");
    await expect(pending).toHaveCount(1);
    await expect(pending).toContainText("q3_regional_review.html");
    await expect(pending).toContainText("Still being written");
    // Announced as busy so the in-place resolution is perceivable to AT.
    await expect(pending).toHaveAttribute("aria-busy", "true");
    // The earlier file stays a full ready card.
    await expect(page.getByTestId("chat-artifact-card")).toHaveCount(1);
  });

  test("the pending card resolves in place once the manifest confirms", async ({
    page,
  }) => {
    // 13.4s: the report is mirrored; the SVG write is now in its own
    // pending window (mirrored at 13.6s).
    await page.goto(at(13_400));
    const reportCard = page
      .getByTestId("chat-artifact-card")
      .filter({ hasText: "q3_regional_review.html" });
    await expect(reportCard).toHaveCount(1);
    await expect(reportCard).toContainText("Report");
    await expect(
      reportCard.getByTestId("chat-artifact-card-primary"),
    ).toHaveText("Open");
    await expect(
      page.getByTestId("chat-artifact-card-pending"),
    ).toContainText("q3_growth_by_region.svg");
  });

  test("a single overflow file does not collapse into a grouped stump", async ({
    page,
  }) => {
    // 14.1s: exactly four ready files. Hiding one file behind a "1 more
    // file" header spends more space than it saves — all four stay full.
    await page.goto(at(14_100));
    await waitForHydration(page);
    await expect(page.getByTestId("chat-artifact-card")).toHaveCount(4);
    await expect(page.getByTestId("chat-artifact-card-row")).toHaveCount(0);
  });

  test("five files collapse to three full cards plus two compact rows", async ({
    page,
  }) => {
    // 15.6s: the markdown summary (5th file) is mirrored; the legacy
    // previews have not published yet.
    await page.goto(at(15_600));
    await waitForHydration(page);
    const cards = page.getByTestId("chat-artifact-card");
    await expect(cards).toHaveCount(3);
    await expect(cards.nth(0)).toContainText("q3_growth.py");
    await expect(cards.nth(1)).toContainText("q3_regional_review.html");
    await expect(cards.nth(2)).toContainText("q3_growth_by_region.svg");
    const rows = page.getByTestId("chat-artifact-card-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText("q3_revenue_by_region.csv");
    await expect(
      rows.nth(0).getByTestId("chat-artifact-card-primary"),
    ).toHaveText("Preview");
    await expect(rows.nth(1)).toContainText("q3_summary.md");
  });

  test("end state: covered files defer to the legacy previews; the rest stay full cards", async ({
    page,
  }) => {
    await page.goto(at(21_200));
    await waitForHydration(page);
    const cards = page.getByTestId("chat-artifact-card");
    // The published table (csv) and report (html) previews cover those
    // files — no duplicate cards with different verbs above them.
    await expect(cards).toHaveCount(3);
    await expect(cards.nth(0)).toContainText("q3_growth.py");
    await expect(cards.nth(1)).toContainText("q3_growth_by_region.svg");
    await expect(cards.nth(2)).toContainText("q3_summary.md");
    await expect(page.getByTestId("chat-artifact-card-row")).toHaveCount(0);
    await expect(
      page.getByTestId("chat-artifact-cards"),
    ).not.toContainText("q3_regional_review.html");
    await expect(
      page.getByTestId("chat-artifact-cards"),
    ).not.toContainText("q3_revenue_by_region.csv");
    // The legacy previews still carry the covered files.
    await expect(
      page.getByText("q3_revenue_by_region.csv").first(),
    ).toBeVisible();
    // The Edit at 14.3s updated the script in place — same card, badged
    // once (the meta line shows only the time, no second "Updated").
    await expect(
      cards.nth(0).getByTestId("chat-artifact-card-updated"),
    ).toBeVisible();
    await expect(cards.nth(0)).not.toContainText(/Updated\s*just now/);
    // Timestamps run on the injected replay clock: the file was edited
    // seconds ago in replay time, and the card says so.
    await expect(cards.nth(0)).toContainText("just now");
  });

  test("the image card renders a real inline thumbnail from file content", async ({
    page,
  }) => {
    await page.goto(at(21_200));
    await waitForHydration(page);
    const thumb = page
      .getByTestId("chat-artifact-card")
      .filter({ hasText: "q3_growth_by_region.svg" })
      .getByTestId("chat-artifact-card-thumb")
      .locator("img");
    await expect(thumb).toBeVisible();
    // Not a broken image: the SVG chart actually decoded.
    await expect
      .poll(() =>
        thumb.evaluate((img: HTMLImageElement) => img.naturalWidth),
      )
      .toBeGreaterThan(0);
  });

  test("cards survive a reload of the same frame (rehydration)", async ({
    page,
  }) => {
    await page.goto(at(21_200));
    await expect(page.getByTestId("chat-artifact-card")).toHaveCount(3);
    await page.reload();
    await expect(page.getByTestId("chat-artifact-card")).toHaveCount(3);
    await expect(
      page.getByTestId("chat-artifact-card-pending"),
    ).toHaveCount(0);
  });

  test("the primary action opens the artifacts panel focused on the file", async ({
    page,
  }) => {
    await page.goto(at(21_200));
    await waitForHydration(page);
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
    await page
      .getByTestId("chat-artifact-card")
      .filter({ hasText: "q3_summary.md" })
      .getByTestId("chat-artifact-card-primary")
      .click();
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await expect(page.getByTestId("artifacts-tab-files")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // The harness stubs the viewer; a selected file shows it, not the list.
    await expect(page.getByTestId("chat-file-stub")).toBeVisible();
    await expect(page.getByTestId("artifacts-file-back")).toBeVisible();
  });

  test("whole-card click is the primary action too", async ({ page }) => {
    await page.goto(at(21_200));
    await waitForHydration(page);
    // Click lands on the card body (not the button) — the stretched
    // primary hit area catches it.
    await page
      .getByTestId("chat-artifact-card")
      .filter({ hasText: "q3_growth.py" })
      .click();
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await expect(page.getByTestId("chat-file-stub")).toBeVisible();
  });

  test("the card opens from the keyboard on a single real button", async ({
    page,
  }) => {
    await page.goto(at(21_200));
    await waitForHydration(page);
    const primary = page
      .getByTestId("chat-artifact-card")
      .filter({ hasText: "q3_growth.py" })
      .getByTestId("chat-artifact-card-primary");
    await primary.focus();
    await expect(primary).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await expect(page.getByTestId("chat-file-stub")).toBeVisible();
  });

  test("download fetches the stored bytes through the authenticated helper", async ({
    page,
  }) => {
    await stubFileContent(page);
    // 15.6s: the CSV is a compact row with its own download control.
    await page.goto(at(15_600));
    await waitForHydration(page);
    const downloadPromise = page.waitForEvent("download");
    await page
      .getByTestId("chat-artifact-card-row")
      .filter({ hasText: "q3_revenue_by_region.csv" })
      .getByTestId("chat-artifact-card-download")
      .click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("q3_revenue_by_region.csv");
  });
});
