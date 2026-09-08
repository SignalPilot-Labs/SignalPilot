import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * Conversation replay ("Replay chat" in the header), exercised through the
 * fixture harness at /chats/test. The harness is scrubbed to its end first
 * so the conversation is complete, then the replay re-streams the whole
 * chat on the compressed clock. At the default 5x every fixture gap is
 * under the 10s cap, so replay offset = original offset / 5 (the 24.8s
 * fixture replays in ~5.4s).
 *
 * Inline artifact cards must follow the replay frame the way they follow a
 * live run: none before the Write step that produced the file, then the
 * card right under that step, and gone again when the scrub moves back.
 * Scrubbing renders text instantly; later turns appear at their anchor.
 */

const BASE = process.env.SP_WEB_BASE_URL ?? "http://localhost:3200";
const at = (ms: number, extra = "") =>
  `${BASE}/chats/test?at=${ms}&paused=1${extra}`;
const FIXTURE_END_MS = 24_800;
/** Replay offsets at 5x for original fixture instants. */
const R = (originalMs: number) => Math.round(originalMs / 5 / 100) * 100;
const REPLAY_END_MS = 5_400;

async function waitForHydration(page: Page) {
  await expect(page.getByTestId("chat-test-harness")).toHaveAttribute(
    "data-hydrated",
    "1",
  );
}

/** Drives the replay's range slider the way a user drag does (React listens
 * to the native `input` event; the value must go through the native setter
 * or React's tracker swallows the change). */
async function scrubTo(controls: Locator, ms: number) {
  await controls
    .getByRole("slider", { name: "Replay position" })
    .evaluate((element, value) => {
      const input = element as HTMLInputElement;
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      setter?.call(input, String(value));
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }, ms);
}

/** Opens the conversation replay and pauses it at once so frames are
 * chosen by the scrub, not by the wall clock. */
async function startPausedReplay(page: Page, extra = "") {
  await page.goto(at(FIXTURE_END_MS, extra));
  await waitForHydration(page);
  await page.getByTestId("chat-replay-button").click();
  const replay = page.getByTestId("chat-replay");
  await expect(replay).toBeVisible();
  const controls = replay.getByTestId("chat-replay-controls");
  await controls.getByRole("button", { name: "Pause replay" }).click();
  await expect(
    controls.getByRole("button", { name: "Play replay" }),
  ).toBeVisible();
  return { replay, controls };
}

test.describe("conversation replay: artifact cards (fixture harness)", () => {
  test("no cards at replay start; cards anchor under their steps as the scrub reaches them", async ({
    page,
  }) => {
    const { replay, controls } = await startPausedReplay(page);
    // The per-message action row is gone; the header owns the entry point.
    await expect(page.getByTestId("standalone-chat-messages")).toHaveCount(0);
    // Paused within the first fraction of a second of replay: the user
    // message and the queued answer show, nothing has been written yet.
    await expect(replay.getByText("Which regions drove Q3")).toBeVisible();
    await expect(replay.getByTestId("chat-artifact-card")).toHaveCount(0);
    await expect(replay.getByTestId("chat-artifact-card-pending")).toHaveCount(0);
    await expect(replay.getByTestId("chat-artifact-card-row")).toHaveCount(0);
    await expect(replay.getByTestId("chat-trailing-artifact-cards")).toHaveCount(0);

    // 15.5s of the original run: five files written, each card under its
    // own Write step inside the open group.
    await scrubTo(controls, R(15_500));
    await expect(replay.getByTestId("chat-step-artifact-cards")).toHaveCount(5);
    const cards = replay.getByTestId("chat-artifact-card");
    await expect(cards).toHaveCount(5);
    await expect(cards.nth(0)).toContainText("q3_growth.py");
    await expect(cards.nth(4)).toContainText("q3_summary.md");
    await expect(replay.getByTestId("chat-trailing-artifact-cards")).toHaveCount(0);
    await expect(replay.getByTestId("chat-artifact-card-pending")).toHaveCount(0);
    // Timestamps run on the replay clock, not today's: the frame is seconds
    // after the edit, so the card says so.
    await expect(cards.nth(0)).toContainText("just now");

    // 12.5s of the original run: the report's Write has landed but its
    // mirror (13.0s) has not — a pending card, under the Write step,
    // exactly as live.
    await scrubTo(controls, R(12_500));
    const pending = replay.getByTestId("chat-artifact-card-pending");
    await expect(pending).toHaveCount(1);
    await expect(pending).toContainText("q3_regional_review.html");
    await expect(
      replay
        .getByTestId("chat-step-artifact-cards")
        .filter({ hasText: "q3_regional_review.html" }),
    ).toHaveCount(1);
    await expect(replay.getByTestId("chat-artifact-card")).toHaveCount(1);

    // Scrub back before the first Write (8s original): the files are gone
    // again, not stranded as trailing cards.
    await scrubTo(controls, R(8_000));
    await expect(replay.getByTestId("chat-artifact-card")).toHaveCount(0);
    await expect(replay.getByTestId("chat-artifact-card-pending")).toHaveCount(0);
    await expect(replay.getByTestId("chat-trailing-artifact-cards")).toHaveCount(0);

    // End of the replay: the run completes, the group collapses and hoists
    // every card into its footer, none trailing — the live end state.
    await scrubTo(controls, REPLAY_END_MS);
    await expect(replay.getByTestId("chat-group-artifact-cards")).toHaveCount(1);
    await expect(replay.getByTestId("chat-artifact-card")).toHaveCount(3);
    // 3 full cards, then the rest as compact rows: the four original files
    // plus the dashboard fixture (spec + two dataset files).
    await expect(replay.getByTestId("chat-artifact-card-row")).toHaveCount(7);
    await expect(replay.getByTestId("chat-trailing-artifact-cards")).toHaveCount(0);
    await expect(replay.getByTestId("chat-step-artifact-cards")).toHaveCount(0);
  });

  test("changing the speed mid-run keeps the same frame and the same cards", async ({
    page,
  }) => {
    const { replay, controls } = await startPausedReplay(page);
    await scrubTo(controls, R(15_500));
    await expect(replay.getByTestId("chat-step-artifact-cards")).toHaveCount(5);
    await expect(controls.getByTestId("chat-replay-speed-5")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await controls.getByTestId("chat-replay-speed-10").click();
    await expect(controls.getByTestId("chat-replay-speed-10")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // Same instant of the original run: the five cards stay, nothing
    // pending, and the clock reads half the elapsed.
    await expect(replay.getByTestId("chat-step-artifact-cards")).toHaveCount(5);
    await expect(replay.getByTestId("chat-artifact-card")).toHaveCount(5);
    await expect(replay.getByTestId("chat-artifact-card-pending")).toHaveCount(0);
    await expect(
      controls.getByRole("slider", { name: "Replay position" }),
    ).toHaveValue(String(Math.round(15_500 / 10 / 100) * 100));
    await controls.getByTestId("chat-replay-speed-2").click();
    await expect(replay.getByTestId("chat-step-artifact-cards")).toHaveCount(5);
    await expect(replay.getByTestId("chat-artifact-card")).toHaveCount(5);
    // Still paused: a speed change never starts playback.
    await expect(
      controls.getByRole("button", { name: "Play replay" }),
    ).toBeVisible();
  });

  test("scrubbing to the end renders the final answer at once, with no caret", async ({
    page,
  }) => {
    const { replay, controls } = await startPausedReplay(page);
    await scrubTo(controls, REPLAY_END_MS);
    // The last streamed sentence is present on the very frame, not typed in.
    await expect(replay).toContainText("so they are unaffected", {
      timeout: 1_000,
    });
    await expect(replay.locator('[data-caret="true"]')).toHaveCount(0);
    await expect(replay.getByTestId("chat-live-indicator")).toHaveCount(0);
    // And stays that way: no smoothing drains text after the fact.
    await page.waitForTimeout(600);
    await expect(replay.locator('[data-caret="true"]')).toHaveCount(0);
    await expect(replay).toContainText("so they are unaffected");
  });

  test("a later turn's user message appears only once its anchor is reached", async ({
    page,
  }) => {
    // ?followup=1 adds a second turn a minute after the first run ended;
    // the replay collapses that pause to the 10s cap.
    const { replay, controls } = await startPausedReplay(page, "&followup=1");
    const followUp = replay.getByText("Project Q4 from these growth rates.");
    await scrubTo(controls, REPLAY_END_MS);
    await expect(replay).toContainText("so they are unaffected");
    await expect(followUp).toHaveCount(0);
    // Past the capped pause: the second turn is on screen.
    await scrubTo(controls, REPLAY_END_MS + 10_000);
    await expect(followUp).toBeVisible();
  });

  test("a replayed card still opens the artifacts panel on its file", async ({
    page,
  }) => {
    const { replay, controls } = await startPausedReplay(page);
    await scrubTo(controls, R(15_500));
    await replay
      .getByTestId("chat-artifact-card")
      .filter({ hasText: "q3_summary.md" })
      .getByTestId("chat-artifact-card-primary")
      .click();
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible();
    await expect(page.getByTestId("artifacts-tab-files")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByTestId("chat-file-stub")).toBeVisible();
  });

  test("while playing, the first ready card pops the artifacts panel open on its file", async ({
    page,
  }) => {
    await page.goto(at(FIXTURE_END_MS));
    await waitForHydration(page);
    // At the end frame the notebook has already ended, so the harness did
    // not auto-open the panel; close it if it is open so the pop-up is
    // observable.
    const close = page.getByTestId("live-notebook-close");
    if (await close.count()) await close.click();
    await expect(page.getByTestId("live-notebook-panel")).toHaveCount(0);
    await page.getByTestId("chat-replay-button").click();
    const replay = page.getByTestId("chat-replay");
    await expect(replay).toBeVisible();
    // The first file (q3_growth.py, 9.2s original) is ready ~1.8s in.
    await expect(page.getByTestId("live-notebook-panel")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("artifacts-tab-files")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByTestId("chat-file-stub")).toBeVisible();
    await expect(
      replay.getByTestId("chat-artifact-card").first(),
    ).toContainText("q3_growth.py");
    // Exit returns the live transcript.
    await replay.getByRole("button", { name: "Exit replay" }).click();
    await expect(page.getByTestId("chat-replay")).toHaveCount(0);
    await expect(page.getByTestId("standalone-chat-messages")).toBeVisible();
  });
});
