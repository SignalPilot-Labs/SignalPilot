"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type {
  ConversationFileInfo,
  StandaloneChatEvent,
  StandaloneChatRunStatus,
} from "~/lib/api";
import type { UiMessage } from "~/components/chat/chat-ui-context";
import {
  filesChangedNamedPaths,
  pathsMatch,
  toolTouchPaths,
} from "~/lib/chat-artifact-cards";

/**
 * Replay of a whole conversation: every run's events and the user messages
 * are rescheduled onto one compressed clock that preserves the original
 * rhythm. Gaps play `speed` times faster and no single wait (a tool call,
 * a long think, the hours between two turns) exceeds REPLAY_MAX_GAP_MS of
 * replay time regardless of speed — the cap bounds the wait the viewer
 * sits through, so a faster speed only shortens the gaps under the cap.
 */

export const REPLAY_SPEEDS = [2, 5, 10] as const;
export type ReplaySpeed = (typeof REPLAY_SPEEDS)[number];
export const DEFAULT_REPLAY_SPEED: ReplaySpeed = 5;
export const REPLAY_MAX_GAP_MS = 10_000;
/** Gap assumed when an item has an unparsable timestamp (already scaled). */
const FALLBACK_GAP_MS = 150;
/** Breathing room after the last item before the replay reports finished. */
const TAIL_MS = 400;

export type ReplaySource = {
  messages: UiMessage[];
  events: StandaloneChatEvent[];
};

export type ScheduledReplayItem = {
  /** Milliseconds from replay start at which this item becomes visible. */
  at: number;
  event?: StandaloneChatEvent;
  message?: UiMessage;
};

export type ReplaySchedule = {
  items: ScheduledReplayItem[];
  totalMs: number;
  /** Piecewise map from original epoch-ms to replay offsets. */
  anchors: { originalMs: number; at: number }[];
  speed: number;
  messages: UiMessage[];
};

export function replayRunId(message: UiMessage): string {
  return (
    message.runId ??
    (typeof message.metadata.run_id === "string" ? message.metadata.run_id : "")
  );
}

/** A conversation is replayable once some run recorded a real event. */
export function canReplayConversation(events: StandaloneChatEvent[]): boolean {
  return events.some((event) => event.type !== "status");
}

function messageOriginalMs(message: UiMessage): number {
  return message.created_at > 0 ? message.created_at * 1_000 : NaN;
}

/**
 * The items in the order they happened: each user message, then the
 * events of the run that answered it (assistant messages whose run has no
 * events stand in for themselves); runs no message claims trail in
 * first-seen order so nothing recorded is lost.
 */
function replayItemOrder(
  source: ReplaySource,
): { originalMs: number; event?: StandaloneChatEvent; message?: UiMessage }[] {
  const byRun = new Map<string, StandaloneChatEvent[]>();
  for (const event of source.events) {
    const list = byRun.get(event.run_id);
    if (list) list.push(event);
    else byRun.set(event.run_id, [event]);
  }
  for (const list of byRun.values()) list.sort((a, b) => a.sequence - b.sequence);
  const eventItem = (event: StandaloneChatEvent) => ({
    originalMs: Date.parse(event.created_at),
    event,
  });
  const items: ReturnType<typeof replayItemOrder> = [];
  const consumed = new Set<string>();
  for (const message of source.messages) {
    const runEvents =
      message.role === "assistant" ? byRun.get(replayRunId(message)) : undefined;
    if (runEvents?.length) {
      consumed.add(replayRunId(message));
      items.push(...runEvents.map(eventItem));
    } else {
      items.push({ originalMs: messageOriginalMs(message), message });
    }
  }
  for (const [runId, runEvents] of byRun) {
    if (!consumed.has(runId)) items.push(...runEvents.map(eventItem));
  }
  return items;
}

export function buildReplaySchedule(
  source: ReplaySource,
  speed: number = DEFAULT_REPLAY_SPEED,
): ReplaySchedule {
  const items: ScheduledReplayItem[] = [];
  const anchors: ReplaySchedule["anchors"] = [];
  let at = 0;
  let previousMs: number | null = null;
  for (const { originalMs, event, message } of replayItemOrder(source)) {
    if (previousMs != null) {
      const gap = Number.isFinite(originalMs)
        ? Math.max(0, originalMs - previousMs)
        : NaN;
      at += Number.isFinite(gap)
        ? Math.min(gap / speed, REPLAY_MAX_GAP_MS)
        : FALLBACK_GAP_MS;
    }
    if (Number.isFinite(originalMs)) {
      anchors.push({ originalMs, at });
      previousMs = originalMs;
    }
    items.push({ at, event, message });
  }
  return {
    items,
    totalMs: items.length ? items[items.length - 1].at + TAIL_MS : 0,
    anchors,
    speed,
    messages: source.messages,
  };
}

/** Maps an original wall-clock instant onto the compressed replay clock. */
export function replayOffsetFor(
  schedule: ReplaySchedule,
  originalMs: number,
): number {
  const { anchors, totalMs, speed } = schedule;
  if (!anchors.length || !Number.isFinite(originalMs)) return totalMs;
  if (originalMs <= anchors[0].originalMs) return 0;
  let last = anchors[0];
  for (const anchor of anchors) {
    if (anchor.originalMs > originalMs) break;
    last = anchor;
  }
  return Math.min(
    last.at +
      Math.min((originalMs - last.originalMs) / speed, REPLAY_MAX_GAP_MS),
    totalMs,
  );
}

/**
 * Inverse of `replayOffsetFor`: the original wall-clock instant (epoch ms)
 * the replay is showing at `elapsed`. Between anchors the clock advances at
 * the schedule's speed from the last anchor and never overtakes the next
 * one (a capped gap fast-forwards to it); past the last item it runs on
 * through the tail. Null when nothing carries a parsable timestamp.
 */
export function replayInstantFor(
  schedule: ReplaySchedule,
  elapsed: number,
): number | null {
  const { anchors, totalMs, speed } = schedule;
  if (!anchors.length) return null;
  const clamped = Math.min(Math.max(elapsed, 0), totalMs);
  let last = anchors[0];
  let next: ReplaySchedule["anchors"][number] | null = null;
  for (const anchor of anchors) {
    if (anchor.at <= clamped) {
      last = anchor;
    } else {
      next = anchor;
      break;
    }
  }
  const projected = Math.max(
    last.originalMs,
    last.originalMs + (clamped - last.at) * speed,
  );
  return next ? Math.min(projected, next.originalMs) : projected;
}

/**
 * The elapsed offset on `to` that shows the same original instant `from`
 * shows at `elapsed` — how a speed change keeps its place in the run.
 */
export function remapReplayElapsed(
  from: ReplaySchedule,
  to: ReplaySchedule,
  elapsed: number,
): number {
  if (from.totalMs > 0 && elapsed >= from.totalMs) return to.totalMs;
  const instant = replayInstantFor(from, elapsed);
  if (instant === null) {
    return from.totalMs > 0 ? (elapsed / from.totalMs) * to.totalMs : 0;
  }
  return replayOffsetFor(to, instant);
}

export type ReplayFrame = {
  visibleEvents: StandaloneChatEvent[];
  /** The transcript at this instant: message status and content follow
   * the frame, so each turn renders as it did live. */
  messages: UiMessage[];
  /** Runs the replay covers (those with events in the schedule). */
  runIds: Set<string>;
  /** Runs whose every event is visible. */
  finishedRunIds: Set<string>;
};

function terminalStatus(message: UiMessage): StandaloneChatRunStatus {
  return (
    message.runStatus ??
    (typeof message.metadata.status === "string"
      ? (message.metadata.status as StandaloneChatRunStatus)
      : "completed")
  );
}

/**
 * What the transcript shows at `elapsed`. A user message appears at its
 * anchor. An assistant turn appears as soon as the message before it is
 * visible ("queued", as live), runs while its events stream in, and takes
 * its real terminal status once the last one is visible. Runs that
 * streamed text rebuild the answer from the replayed deltas (content
 * empty); runs that only produced a final message reveal it on completion.
 */
export function deriveReplayFrame(
  schedule: ReplaySchedule,
  elapsed: number,
): ReplayFrame {
  const visibleEvents: StandaloneChatEvent[] = [];
  const visibleMessageIds = new Set<string>();
  const total = new Map<string, number>();
  const seen = new Map<string, number>();
  const streamed = new Set<string>();
  for (const item of schedule.items) {
    if (item.event) {
      const runId = item.event.run_id;
      total.set(runId, (total.get(runId) ?? 0) + 1);
      if (item.event.type === "text_delta") streamed.add(runId);
      if (item.at <= elapsed) {
        visibleEvents.push(item.event);
        seen.set(runId, (seen.get(runId) ?? 0) + 1);
      }
    } else if (item.message && item.at <= elapsed) {
      visibleMessageIds.add(item.message.id);
    }
  }
  const runIds = new Set(total.keys());
  const finishedRunIds = new Set<string>();
  for (const [runId, count] of total) {
    if ((seen.get(runId) ?? 0) >= count) finishedRunIds.add(runId);
  }
  const messages: UiMessage[] = [];
  schedule.messages.forEach((message, index) => {
    const runId = message.role === "assistant" ? replayRunId(message) : "";
    if (!runId || !runIds.has(runId)) {
      if (visibleMessageIds.has(message.id)) messages.push(message);
      return;
    }
    const started = (seen.get(runId) ?? 0) > 0;
    const previousVisible =
      index > 0 && messages[messages.length - 1]?.id === schedule.messages[index - 1].id;
    if (!started && !previousVisible) return;
    const finished = finishedRunIds.has(runId);
    messages.push({
      ...message,
      runId,
      runStatus: finished ? terminalStatus(message) : started ? "running" : "queued",
      content: !streamed.has(runId) && finished ? message.content : "",
    });
  });
  return { visibleEvents, messages, runIds, finishedRunIds };
}

/**
 * The slice of the file manifest a replay frame may show. A file appears
 * the way it did live: once a visible `files_changed` of its run names its
 * path (the mirror confirmed it) or, for a path no capture event ever
 * confirms, once the visible Write/Edit step that produced it lands. Files
 * nothing in the run touches (the run-end sweep) appear when the run's
 * last event is visible. Files of runs the replay does not cover pass
 * through. Derived from `visibleEvents`, so scrubbing back hides files.
 */
export function replayVisibleFiles(
  files: ConversationFileInfo[],
  opts: {
    /** Every event of the conversation, for "was this path ever confirmed". */
    events: StandaloneChatEvent[];
    visibleEvents: StandaloneChatEvent[];
  },
): ConversationFileInfo[] {
  const { events, visibleEvents } = opts;
  const total = new Map<string, number>();
  const confirmedEver = new Map<string, string[]>();
  for (const event of events) {
    total.set(event.run_id, (total.get(event.run_id) ?? 0) + 1);
    if (event.type !== "files_changed") continue;
    const list = confirmedEver.get(event.run_id) ?? [];
    list.push(...filesChangedNamedPaths(event));
    confirmedEver.set(event.run_id, list);
  }
  const seen = new Map<string, number>();
  const confirmedNow = new Map<string, string[]>();
  const writtenNow = new Map<string, string[]>();
  for (const event of visibleEvents) {
    seen.set(event.run_id, (seen.get(event.run_id) ?? 0) + 1);
    const target =
      event.type === "files_changed"
        ? confirmedNow
        : event.type === "tool_started"
          ? writtenNow
          : null;
    if (!target) continue;
    const paths =
      event.type === "files_changed"
        ? filesChangedNamedPaths(event)
        : toolTouchPaths(event);
    if (!paths.length) continue;
    const list = target.get(event.run_id) ?? [];
    list.push(...paths);
    target.set(event.run_id, list);
  }
  const matches = (paths: string[] | undefined, path: string) =>
    (paths ?? []).some(
      (candidate) => candidate === path || pathsMatch(candidate, path),
    );
  return files.filter((file) => {
    const runId = file.origin_run_id;
    if (!runId || !total.has(runId)) return true;
    if ((seen.get(runId) ?? 0) >= (total.get(runId) ?? 0)) return true;
    if (matches(confirmedNow.get(runId), file.path)) return true;
    if (matches(confirmedEver.get(runId), file.path)) return false;
    return matches(writtenNow.get(runId), file.path);
  });
}

export type ConversationReplayState = {
  elapsed: number;
  totalMs: number;
  playing: boolean;
  finished: boolean;
  speed: ReplaySpeed;
  setSpeed: (speed: ReplaySpeed) => void;
  frame: ReplayFrame;
  /** The original wall-clock instant the frame shows; undefined when
   * nothing carries a parsable timestamp (callers fall back to live time). */
  nowMs: number | undefined;
  /** Bumps every time the replay starts over from the beginning. */
  session: number;
  /** True when the frame was not reached by playback (paused or scrubbed):
   * every visible text block renders complete, with no caret. */
  textInstant: boolean;
  togglePlay: () => void;
  restart: () => void;
  scrub: (ms: number) => void;
};

const TICK_MS = 50;

export function useConversationReplay(
  source: ReplaySource,
): ConversationReplayState {
  const { messages, events } = source;
  const [speed, setSpeedState] = useState<ReplaySpeed>(DEFAULT_REPLAY_SPEED);
  const schedule = useMemo(
    () => buildReplaySchedule({ messages, events }, speed),
    [messages, events, speed],
  );
  const [elapsed, setElapsed] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [session, setSession] = useState(0);
  const totalMs = schedule.totalMs;
  const finished = elapsed >= totalMs;
  // The clock runs only while playing and not yet at the end; reaching the
  // end stops it without a separate state write.
  const ticking = playing && !finished;

  useEffect(() => {
    if (!ticking) return;
    const interval = window.setInterval(() => {
      setElapsed((value) => Math.min(value + TICK_MS, totalMs));
    }, TICK_MS);
    return () => window.clearInterval(interval);
  }, [ticking, totalMs]);

  const frame = useMemo(
    () => deriveReplayFrame(schedule, elapsed),
    [schedule, elapsed],
  );
  const nowMs = useMemo(
    () => replayInstantFor(schedule, elapsed) ?? undefined,
    [schedule, elapsed],
  );
  const restart = () => {
    setElapsed(0);
    setSession((value) => value + 1);
    setPlaying(true);
  };
  return {
    elapsed,
    totalMs,
    playing: ticking,
    finished,
    speed,
    setSpeed: (next) => {
      if (next === speed) return;
      // Stay at the same point of the original run: map the current
      // offset back to its instant and forward onto the new clock.
      const nextSchedule = buildReplaySchedule({ messages, events }, next);
      setElapsed(remapReplayElapsed(schedule, nextSchedule, elapsed));
      setSpeedState(next);
    },
    frame,
    nowMs,
    session,
    textInstant: !ticking,
    togglePlay: () => {
      // Play from the end starts the run over.
      if (finished) restart();
      else setPlaying((value) => !value);
    },
    restart,
    scrub: (ms: number) => {
      setPlaying(false);
      setElapsed(Math.min(Math.max(ms, 0), totalMs));
    },
  };
}

/**
 * The replay's "pop up": the first time a file of a replayed run becomes
 * ready while the replay is playing, open the artifacts panel on it, once
 * per file per replay session. Files already visible when a session starts
 * or when playback resumes after a pause or a scrub are absorbed silently,
 * so scrubbing never opens the panel; a restart clears the memory.
 */
export function useReplayArtifactAutoOpen({
  files,
  runIds,
  playing,
  session,
  openArtifact,
}: {
  /** The frame's visible manifest (see `replayVisibleFiles`). */
  files: ConversationFileInfo[];
  /** Runs the replay covers; files of other runs never pop. */
  runIds: ReadonlySet<string>;
  playing: boolean;
  session: number;
  openArtifact: (fileId: string) => void;
}): void {
  const seenRef = useRef<{ session: number; ids: Set<string> } | null>(null);
  // Latest opener without re-running the reveal effect on identity churn.
  const openRef = useRef(openArtifact);
  useEffect(() => {
    openRef.current = openArtifact;
  }, [openArtifact]);
  useEffect(() => {
    // A fresh session absorbs its opening frame silently.
    const fresh = seenRef.current === null || seenRef.current.session !== session;
    if (fresh) seenRef.current = { session, ids: new Set() };
    const seen = seenRef.current!.ids;
    for (const file of files) {
      if (!file.origin_run_id || !runIds.has(file.origin_run_id)) continue;
      if (file.status !== "active" || seen.has(file.id)) continue;
      seen.add(file.id);
      if (playing && !fresh) openRef.current(file.id);
    }
  }, [files, runIds, playing, session]);
}
