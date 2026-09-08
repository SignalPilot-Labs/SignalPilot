import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversationFileInfo, StandaloneChatEvent } from "~/lib/api";
import type { UiMessage } from "~/components/chat/chat-ui-context";
import {
  buildReplaySchedule,
  canReplayConversation,
  DEFAULT_REPLAY_SPEED,
  deriveReplayFrame,
  REPLAY_MAX_GAP_MS,
  remapReplayElapsed,
  replayInstantFor,
  replayOffsetFor,
  replayVisibleFiles,
  useReplayArtifactAutoOpen,
} from "~/lib/chat-replay";

const BASE = Date.UTC(2026, 0, 1, 12, 0, 0);
const SPEED = DEFAULT_REPLAY_SPEED;

function event(
  sequence: number,
  offsetMs: number,
  type: StandaloneChatEvent["type"] = "progress",
  runId = "run-1",
  payload: StandaloneChatEvent["payload"] = {},
): StandaloneChatEvent {
  return {
    run_id: runId,
    sequence,
    type,
    payload,
    created_at: new Date(BASE + offsetMs).toISOString(),
  };
}

function user(id: string, offsetMs: number, content = "q"): UiMessage {
  return {
    id,
    role: "user",
    content,
    sequence: 0,
    created_at: (BASE + offsetMs) / 1_000,
    metadata: {},
  };
}

function assistant(
  id: string,
  runId: string,
  offsetMs: number,
  content = "answer",
  runStatus: UiMessage["runStatus"] = "completed",
): UiMessage {
  return {
    id,
    role: "assistant",
    content,
    sequence: 0,
    created_at: (BASE + offsetMs) / 1_000,
    metadata: { run_id: runId },
    runId,
    runStatus,
  };
}

const eventsOnly = (events: StandaloneChatEvent[]) => ({ messages: [], events });

describe("buildReplaySchedule", () => {
  it("scales gaps by the speed and preserves order", () => {
    const schedule = buildReplaySchedule(
      eventsOnly([event(1, 0), event(2, 2_000), event(3, 10_000)]),
      SPEED,
    );
    expect(schedule.items.map((item) => item.at)).toEqual([
      0,
      2_000 / SPEED,
      2_000 / SPEED + 8_000 / SPEED,
    ]);
    expect(schedule.speed).toBe(SPEED);
  });

  it("caps any single wait at 10 seconds regardless of speed", () => {
    // A 15-minute tool call still replays in 10s, at 2x and at 10x.
    for (const speed of [2, 10]) {
      const schedule = buildReplaySchedule(
        eventsOnly([
          event(1, 0, "tool_started"),
          event(2, 15 * 60_000, "tool_completed"),
        ]),
        speed,
      );
      expect(schedule.items[1].at).toBe(REPLAY_MAX_GAP_MS);
    }
  });

  it("unparsable timestamps fall back to a small gap", () => {
    const broken: StandaloneChatEvent = {
      run_id: "run-1",
      sequence: 2,
      type: "progress",
      payload: {},
      created_at: "not-a-date",
    };
    const schedule = buildReplaySchedule(
      eventsOnly([event(1, 0), broken, event(3, 1_000)]),
      SPEED,
    );
    expect(schedule.items).toHaveLength(3);
    expect(schedule.items[1].at).toBeGreaterThan(0);
    expect(schedule.items[2].at).toBeGreaterThanOrEqual(1_000 / SPEED);
  });

  it("orders a conversation as it happened: user, run, user, run", () => {
    const messages = [
      user("u1", 0),
      assistant("a1", "run-1", 5_000),
      // Two hours later.
      user("u2", 7_200_000),
      assistant("a2", "run-2", 7_205_000),
    ];
    const events = [
      event(1, 1_000, "progress", "run-1"),
      event(2, 4_000, "text_delta", "run-1"),
      event(1, 7_201_000, "progress", "run-2"),
      event(2, 7_204_000, "text_delta", "run-2"),
    ];
    const schedule = buildReplaySchedule({ messages, events }, SPEED);
    expect(
      schedule.items.map((item) => item.message?.id ?? item.event?.run_id),
    ).toEqual(["u1", "run-1", "run-1", "u2", "run-2", "run-2"]);
    // The pause between turns collapses to the cap.
    expect(schedule.items[3].at - schedule.items[2].at).toBe(REPLAY_MAX_GAP_MS);
    expect(schedule.items[1].at).toBe(1_000 / SPEED);
    // Assistant messages with events are represented by their run, not
    // scheduled themselves.
    expect(schedule.items.some((item) => item.message?.id === "a1")).toBe(false);
  });

  it("schedules an assistant message with no events on its own timestamp", () => {
    const messages = [user("u1", 0), assistant("a1", "run-1", 3_000)];
    const schedule = buildReplaySchedule({ messages, events: [] }, SPEED);
    expect(schedule.items.map((item) => item.message?.id)).toEqual(["u1", "a1"]);
    expect(schedule.items[1].at).toBe(3_000 / SPEED);
  });

  it("keeps events of runs no message claims", () => {
    const schedule = buildReplaySchedule(
      { messages: [user("u1", 0)], events: [event(1, 500, "progress", "orphan")] },
      SPEED,
    );
    expect(schedule.items).toHaveLength(2);
  });
});

describe("canReplayConversation", () => {
  it("needs at least one non-status event", () => {
    expect(canReplayConversation([])).toBe(false);
    expect(canReplayConversation([event(1, 0, "status")])).toBe(false);
    expect(canReplayConversation([event(1, 0, "status"), event(2, 1, "progress")])).toBe(true);
  });
});

describe("replayOffsetFor / replayInstantFor", () => {
  const schedule = buildReplaySchedule(
    eventsOnly([event(1, 0), event(2, 60_000), event(3, 62_000)]),
    SPEED,
  );

  it("maps instants between events onto the compressed clock", () => {
    expect(replayOffsetFor(schedule, BASE)).toBe(0);
    expect(replayOffsetFor(schedule, BASE + 61_000)).toBe(
      REPLAY_MAX_GAP_MS + 1_000 / SPEED,
    );
    expect(replayOffsetFor(schedule, BASE - 5_000)).toBe(0);
    expect(replayOffsetFor(schedule, BASE + 10 * 60_000)).toBe(schedule.totalMs);
  });

  it("returns the original instant at every anchor (inverse of replayOffsetFor)", () => {
    for (const anchor of schedule.anchors) {
      expect(replayInstantFor(schedule, anchor.at)).toBe(anchor.originalMs);
      expect(replayOffsetFor(schedule, anchor.originalMs)).toBe(anchor.at);
    }
  });

  it("interpolates at the schedule speed between anchors", () => {
    const secondAt = schedule.anchors[1].at;
    expect(replayInstantFor(schedule, secondAt + 200)).toBe(
      BASE + 60_000 + 200 * SPEED,
    );
    expect(replayOffsetFor(schedule, BASE + 61_000)).toBe(secondAt + 200);
  });

  it("never overtakes the next anchor inside a capped wait", () => {
    expect(replayInstantFor(schedule, 9_900)).toBe(BASE + 9_900 * SPEED);
    expect(replayInstantFor(schedule, REPLAY_MAX_GAP_MS)).toBe(BASE + 60_000);
  });

  it("clamps before the start and runs through the tail after the last event", () => {
    expect(replayInstantFor(schedule, -500)).toBe(BASE);
    const lastAt = schedule.anchors[2].at;
    expect(replayInstantFor(schedule, lastAt + 100)).toBe(
      BASE + 62_000 + 100 * SPEED,
    );
    expect(replayInstantFor(schedule, schedule.totalMs + 5_000)).toBe(
      BASE + 62_000 + (schedule.totalMs - lastAt) * SPEED,
    );
  });

  it("is null when nothing has a parsable timestamp", () => {
    const schedule = buildReplaySchedule(
      eventsOnly([{ ...event(1, 0), created_at: "nope" }]),
      SPEED,
    );
    expect(replayInstantFor(schedule, 0)).toBeNull();
  });
});

describe("remapReplayElapsed", () => {
  const source = eventsOnly([
    event(1, 0),
    event(2, 4_000, "tool_started"),
    event(3, 8_000, "tool_completed"),
    event(4, 12_000, "text_delta"),
  ]);
  const at5 = buildReplaySchedule(source, 5);
  const at10 = buildReplaySchedule(source, 10);
  const at2 = buildReplaySchedule(source, 2);

  it("keeps the same original instant when the speed changes", () => {
    // 6s into the run at 5x = 1.2s of replay; at 10x the same instant is 0.6s.
    expect(replayInstantFor(at5, 1_200)).toBe(BASE + 6_000);
    expect(remapReplayElapsed(at5, at10, 1_200)).toBe(600);
    expect(replayInstantFor(at10, 600)).toBe(BASE + 6_000);
    // And back out to 2x: 3s of replay.
    expect(remapReplayElapsed(at10, at2, 600)).toBe(3_000);
    expect(replayInstantFor(at2, 3_000)).toBe(BASE + 6_000);
  });

  it("keeps the same visible items across a speed change", () => {
    const visibleAt = (schedule: typeof at5, elapsed: number) =>
      schedule.items.filter((item) => item.at <= elapsed).length;
    for (const elapsed of [0, 700, 1_650, 2_400]) {
      expect(visibleAt(at10, remapReplayElapsed(at5, at10, elapsed))).toBe(
        visibleAt(at5, elapsed),
      );
    }
  });

  it("maps the end to the end", () => {
    expect(remapReplayElapsed(at5, at10, at5.totalMs)).toBe(at10.totalMs);
    expect(remapReplayElapsed(at5, at10, 0)).toBe(0);
  });
});

describe("deriveReplayFrame", () => {
  const messages = [
    user("u1", 0, "first question"),
    assistant("a1", "run-1", 5_000, "persisted answer"),
    user("u2", 60_000, "second question"),
    assistant("a2", "run-2", 65_000, "final answer"),
    assistant("a3", "run-3", 70_000, "no events"),
  ];
  const events = [
    event(1, 1_000, "progress", "run-1"),
    event(2, 4_000, "progress", "run-1"),
    event(1, 61_000, "progress", "run-2"),
    event(2, 64_000, "text_delta", "run-2", { delta: "final" }),
  ];
  const schedule = buildReplaySchedule({ messages, events }, SPEED);
  const ids = (elapsed: number) =>
    deriveReplayFrame(schedule, elapsed).messages.map((m) => m.id);
  const status = (elapsed: number, id: string) =>
    deriveReplayFrame(schedule, elapsed).messages.find((m) => m.id === id)?.runStatus;

  it("shows a user message at its anchor and its answer as queued right after", () => {
    expect(ids(0)).toEqual(["u1", "a1"]);
    expect(status(0, "a1")).toBe("queued");
  });

  it("runs a turn while its events stream and settles to the real status", () => {
    const first = schedule.items[1].at;
    expect(status(first, "a1")).toBe("running");
    expect(deriveReplayFrame(schedule, first).finishedRunIds.has("run-1")).toBe(false);
    const last = schedule.items[2].at;
    expect(status(last, "a1")).toBe("completed");
    expect(deriveReplayFrame(schedule, last).finishedRunIds.has("run-1")).toBe(true);
  });

  it("reveals persisted content on completion only for runs that did not stream text", () => {
    const first = schedule.items[1].at;
    const done1 = schedule.items[2].at;
    const content = (elapsed: number, id: string) =>
      deriveReplayFrame(schedule, elapsed).messages.find((m) => m.id === id)?.content;
    expect(content(first, "a1")).toBe("");
    expect(content(done1, "a1")).toBe("persisted answer");
    // run-2 streamed deltas: the blocks rebuild it, the message stays empty.
    expect(content(schedule.totalMs, "a2")).toBe("");
  });

  it("hides a later turn until its anchor, then shows it", () => {
    const u2At = schedule.items.find((item) => item.message?.id === "u2")!.at;
    expect(ids(u2At - 1)).toEqual(["u1", "a1"]);
    expect(ids(u2At)).toEqual(["u1", "a1", "u2", "a2"]);
    expect(status(u2At, "a2")).toBe("queued");
  });

  it("shows an eventless assistant message at its own anchor, as is", () => {
    const a3At = schedule.items.find((item) => item.message?.id === "a3")!.at;
    expect(ids(a3At - 1)).not.toContain("a3");
    const frame = deriveReplayFrame(schedule, a3At);
    expect(frame.messages.find((m) => m.id === "a3")?.content).toBe("no events");
    expect(frame.runIds.has("run-3")).toBe(false);
  });
});

const fileRow = (path: string, runId = "run-1"): ConversationFileInfo => ({
  id: `id-${path}`,
  path,
  filename: path.split("/").pop() ?? path,
  kind: "data",
  mime_type: "text/csv",
  byte_size: 10,
  content_hash: "h1",
  origin_run_id: runId,
  origin: "runtime",
  status: "active",
  created_at: new Date(BASE).toISOString(),
  updated_at: new Date(BASE).toISOString(),
});

describe("replayVisibleFiles", () => {
  const writeReport = event(1, 0, "tool_started", "run-1", {
    tool: "Write",
    tool_call_id: "c1",
    input: { file_path: "/workspace/exports/report.html", content: "x" },
  });
  const mirrorReport = event(2, 900, "files_changed", "run-1", {
    changed: ["exports/report.html"],
    deleted: [],
  });
  const writeNotes = event(3, 2_000, "tool_started", "run-1", {
    tool: "Edit",
    tool_call_id: "c2",
    input: { file_path: "notes.md", old_string: "a", new_string: "b" },
  });
  const runCells = event(4, 3_000, "tool_started", "run-1", {
    tool: "mcp__standalone-chat__run_cells",
    tool_call_id: "c3",
    input: { cells: [] },
  });
  const captureChart = event(5, 4_000, "files_changed", "run-1", {
    changed: 1,
    files: [{ path: "artifacts/chart.png", deleted: false }],
    tool_call_id: "c3",
  });
  const done = event(6, 5_000, "status", "run-1", { status: "completed" });
  const otherRun = event(1, 9_000, "progress", "run-2");
  const events = [
    writeReport,
    mirrorReport,
    writeNotes,
    runCells,
    captureChart,
    done,
    otherRun,
  ];
  const files = [
    fileRow("exports/report.html"),
    fileRow("notes.md"),
    fileRow("artifacts/chart.png"),
    fileRow("sweep.csv"),
    fileRow("later.csv", "run-2"),
    fileRow("earlier.csv", "run-0"),
  ];
  const visible = (visibleEvents: StandaloneChatEvent[]) =>
    replayVisibleFiles(files, { events, visibleEvents }).map((file) => file.path);

  it("shows only files of runs the replay does not cover before anything is touched", () => {
    expect(visible([])).toEqual(["earlier.csv"]);
  });

  it("keeps a mirrored file hidden through its pending window, then reveals it", () => {
    expect(visible([writeReport])).toEqual(["earlier.csv"]);
    expect(visible([writeReport, mirrorReport])).toEqual([
      "exports/report.html",
      "earlier.csv",
    ]);
  });

  it("reveals a file no capture ever confirms at its Write/Edit step", () => {
    expect(visible([writeReport, mirrorReport, writeNotes])).toContain("notes.md");
  });

  it("reveals a runtime capture at its files_changed, not at the tool call", () => {
    expect(visible([writeReport, mirrorReport, writeNotes, runCells])).not.toContain(
      "artifacts/chart.png",
    );
    expect(visible([writeReport, mirrorReport, writeNotes, runCells, captureChart])).toContain(
      "artifacts/chart.png",
    );
  });

  it("holds untouched files (the run-end sweep) until the run's last event", () => {
    const beforeDone = [writeReport, mirrorReport, writeNotes, runCells, captureChart];
    expect(visible(beforeDone)).not.toContain("sweep.csv");
    expect(visible([...beforeDone, done])).toContain("sweep.csv");
    // The second run has not started: its file stays hidden.
    expect(visible([...beforeDone, done])).not.toContain("later.csv");
    expect(visible(events)).toEqual(files.map((file) => file.path));
  });

  it("hides a file again when the scrub moves before its touch", () => {
    expect(visible(events)).toContain("notes.md");
    expect(visible([writeReport, mirrorReport])).not.toContain("notes.md");
  });
});

describe("useReplayArtifactAutoOpen", () => {
  (
    globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true;
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const runIds = new Set(["run-1"]);
  function Probe(props: {
    files: ConversationFileInfo[];
    playing: boolean;
    session: number;
    openArtifact: (fileId: string) => void;
  }) {
    useReplayArtifactAutoOpen({ ...props, runIds });
    return null;
  }
  const render = async (
    files: ConversationFileInfo[],
    playing: boolean,
    session: number,
    openArtifact: (fileId: string) => void,
  ) => {
    await act(async () => {
      root.render(createElement(Probe, { files, playing, session, openArtifact }));
    });
  };

  it("opens each covered file once as it becomes ready while playing", async () => {
    const open = vi.fn();
    const a = fileRow("a.csv");
    const b = fileRow("b.csv");
    const other = fileRow("z.csv", "run-0");
    await render([other], true, 0, open);
    expect(open).not.toHaveBeenCalled();
    await render([other, a], true, 0, open);
    expect(open).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenCalledWith("id-a.csv");
    await render([other, a], true, 0, open);
    await render([other, a, b], true, 0, open);
    expect(open).toHaveBeenCalledTimes(2);
    expect(open).toHaveBeenLastCalledWith("id-b.csv");
  });

  it("absorbs the opening frame and files that appear while paused or scrubbed", async () => {
    const open = vi.fn();
    const a = fileRow("a.csv");
    // Mounted with a file already visible (e.g. a pass-through row): no pop.
    await render([a], true, 0, open);
    expect(open).not.toHaveBeenCalled();
    const b = fileRow("b.csv");
    await render([a, b], false, 0, open);
    await render([a, b], true, 0, open);
    expect(open).not.toHaveBeenCalled();
    await render([], false, 0, open);
    await render([a, b], true, 0, open);
    expect(open).not.toHaveBeenCalled();
  });

  it("forgets everything on restart so the next session pops up again", async () => {
    const open = vi.fn();
    const a = fileRow("a.csv");
    await render([], true, 0, open);
    await render([a], true, 0, open);
    expect(open).toHaveBeenCalledTimes(1);
    await render([], true, 1, open);
    await render([a], true, 1, open);
    expect(open).toHaveBeenCalledTimes(2);
  });
});
