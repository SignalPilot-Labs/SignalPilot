import { describe, expect, it } from "vitest";
import type { StandaloneChatEvent } from "~/lib/api";
import {
  buildReplaySchedule,
  REPLAY_MAX_GAP_MS,
  REPLAY_SPEED,
  replayOffsetFor,
} from "~/lib/chat-replay";

const BASE = Date.UTC(2026, 0, 1, 12, 0, 0);

function event(
  sequence: number,
  offsetMs: number,
  type: StandaloneChatEvent["type"] = "progress",
  runId = "run-1",
): StandaloneChatEvent {
  return {
    run_id: runId,
    sequence,
    type,
    payload: {},
    created_at: new Date(BASE + offsetMs).toISOString(),
  };
}

describe("buildReplaySchedule", () => {
  it("scales gaps by 4x and preserves order", () => {
    const schedule = buildReplaySchedule(
      [event(1, 0), event(2, 2_000), event(3, 10_000)],
      "run-1",
    );
    expect(schedule.items.map((item) => item.at)).toEqual([
      0,
      2_000 / REPLAY_SPEED,
      2_000 / REPLAY_SPEED + 8_000 / REPLAY_SPEED,
    ]);
  });

  it("caps any single wait at 10 seconds", () => {
    // A 15-minute tool call still replays in 10s.
    const schedule = buildReplaySchedule(
      [event(1, 0, "tool_started"), event(2, 15 * 60_000, "tool_completed")],
      "run-1",
    );
    expect(schedule.items[1].at).toBe(REPLAY_MAX_GAP_MS);
  });

  it("ignores events from other runs and unparsable timestamps fall back", () => {
    const broken: StandaloneChatEvent = {
      run_id: "run-1",
      sequence: 2,
      type: "progress",
      payload: {},
      created_at: "not-a-date",
    };
    const schedule = buildReplaySchedule(
      [event(1, 0), broken, event(3, 1_000), event(4, 0, "progress", "other")],
      "run-1",
    );
    expect(schedule.items).toHaveLength(3);
    // Broken timestamp uses the small fallback gap; the next parsable event
    // resumes scaling from the last good anchor.
    expect(schedule.items[1].at).toBeGreaterThan(0);
    expect(schedule.items[2].at).toBeGreaterThanOrEqual(
      1_000 / REPLAY_SPEED,
    );
  });

  it("a compressed 15-minute run fits in a demo window", () => {
    // 30 events spread evenly across 15 minutes: each 31s gap → capped well
    // below 10s each, so total is under ~4 minutes.
    const events = Array.from({ length: 30 }, (_, index) =>
      event(index + 1, index * 31_000),
    );
    const schedule = buildReplaySchedule(events, "run-1");
    expect(schedule.totalMs).toBeLessThan(4 * 60_000);
    expect(schedule.totalMs).toBeGreaterThan(60_000);
  });
});

describe("replayOffsetFor", () => {
  const schedule = buildReplaySchedule(
    [event(1, 0), event(2, 60_000), event(3, 62_000)],
    "run-1",
  );

  it("maps instants between events onto the compressed clock", () => {
    // First gap is capped at 10s; an artifact created 30s in maps inside it.
    expect(replayOffsetFor(schedule, BASE)).toBe(0);
    expect(replayOffsetFor(schedule, BASE + 61_000)).toBe(
      REPLAY_MAX_GAP_MS + 1_000 / REPLAY_SPEED,
    );
  });

  it("clamps before the run and after its end", () => {
    expect(replayOffsetFor(schedule, BASE - 5_000)).toBe(0);
    expect(replayOffsetFor(schedule, BASE + 10 * 60_000)).toBe(
      schedule.totalMs,
    );
  });
});
