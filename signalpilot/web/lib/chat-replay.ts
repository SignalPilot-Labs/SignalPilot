"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { StandaloneChatArtifact, StandaloneChatEvent } from "~/lib/api";

/**
 * Replay of a recorded run: events are rescheduled onto a compressed clock
 * that preserves the original rhythm. Every gap between events plays 4x
 * faster, and no single wait (a tool call, a long think) exceeds 10 seconds,
 * so a 15-minute run demos in a couple of minutes without losing its shape.
 */

export const REPLAY_SPEED = 4;
export const REPLAY_MAX_GAP_MS = 10_000;
/** Gap assumed when an event has an unparsable timestamp (already scaled). */
const FALLBACK_GAP_MS = 150;
/** Breathing room after the last event before the replay reports finished. */
const TAIL_MS = 400;

export type ScheduledReplayEvent = {
  event: StandaloneChatEvent;
  /** Milliseconds from replay start at which this event becomes visible. */
  at: number;
};

export type ReplaySchedule = {
  items: ScheduledReplayEvent[];
  totalMs: number;
  /** Piecewise map from original epoch-ms to replay offsets. */
  anchors: { originalMs: number; at: number }[];
};

export function buildReplaySchedule(
  events: StandaloneChatEvent[],
  runId: string,
): ReplaySchedule {
  const runEvents = events
    .filter((event) => event.run_id === runId)
    .sort((a, b) => a.sequence - b.sequence);
  const items: ScheduledReplayEvent[] = [];
  const anchors: ReplaySchedule["anchors"] = [];
  let at = 0;
  let previousMs: number | null = null;
  for (const event of runEvents) {
    const originalMs = Date.parse(event.created_at);
    if (previousMs != null) {
      const gap = Number.isFinite(originalMs)
        ? Math.max(0, originalMs - previousMs)
        : NaN;
      at += Number.isFinite(gap)
        ? Math.min(gap / REPLAY_SPEED, REPLAY_MAX_GAP_MS)
        : FALLBACK_GAP_MS;
    }
    if (Number.isFinite(originalMs)) {
      anchors.push({ originalMs, at });
      previousMs = originalMs;
    }
    items.push({ event, at });
  }
  return {
    items,
    totalMs: items.length ? items[items.length - 1].at + TAIL_MS : 0,
    anchors,
  };
}

/** Maps an original wall-clock instant onto the compressed replay clock. */
export function replayOffsetFor(
  schedule: ReplaySchedule,
  originalMs: number,
): number {
  const { anchors, totalMs } = schedule;
  if (!anchors.length || !Number.isFinite(originalMs)) return totalMs;
  if (originalMs <= anchors[0].originalMs) return 0;
  let last = anchors[0];
  for (const anchor of anchors) {
    if (anchor.originalMs > originalMs) break;
    last = anchor;
  }
  return Math.min(
    last.at +
      Math.min((originalMs - last.originalMs) / REPLAY_SPEED, REPLAY_MAX_GAP_MS),
    totalMs,
  );
}

export type ChatReplayState = {
  elapsed: number;
  totalMs: number;
  playing: boolean;
  finished: boolean;
  visibleEvents: StandaloneChatEvent[];
  visibleArtifacts: StandaloneChatArtifact[];
  togglePlay: () => void;
  restart: () => void;
  scrub: (ms: number) => void;
};

const TICK_MS = 50;

export function useChatReplay(
  events: StandaloneChatEvent[],
  artifacts: StandaloneChatArtifact[],
  runId: string,
): ChatReplayState {
  const schedule = useMemo(
    () => buildReplaySchedule(events, runId),
    [events, runId],
  );
  const [elapsed, setElapsed] = useState(0);
  const [playing, setPlaying] = useState(true);
  const totalRef = useRef(schedule.totalMs);
  totalRef.current = schedule.totalMs;

  useEffect(() => {
    if (!playing) return;
    const interval = window.setInterval(() => {
      setElapsed((value) => {
        const next = value + TICK_MS;
        if (next >= totalRef.current) {
          window.clearInterval(interval);
          return totalRef.current;
        }
        return next;
      });
    }, TICK_MS);
    return () => window.clearInterval(interval);
  }, [playing]);
  const finished = elapsed >= schedule.totalMs;
  useEffect(() => {
    if (finished && playing) setPlaying(false);
  }, [finished, playing]);

  const visibleEvents = useMemo(
    () =>
      schedule.items
        .filter((item) => item.at <= elapsed)
        .map((item) => item.event),
    [schedule, elapsed],
  );
  const artifactTimes = useMemo(
    () =>
      artifacts
        .filter((artifact) => artifact.run_id === runId)
        .map((artifact) => ({
          artifact,
          at: replayOffsetFor(schedule, Date.parse(artifact.created_at)),
        })),
    [artifacts, runId, schedule],
  );
  const visibleArtifacts = useMemo(
    () =>
      artifactTimes
        .filter((item) => item.at <= elapsed)
        .map((item) => item.artifact),
    [artifactTimes, elapsed],
  );

  return {
    elapsed,
    totalMs: schedule.totalMs,
    playing,
    finished,
    visibleEvents,
    visibleArtifacts,
    togglePlay: () => {
      if (elapsed >= totalRef.current) setElapsed(0);
      setPlaying((value) => !value);
    },
    restart: () => {
      setElapsed(0);
      setPlaying(true);
    },
    scrub: (ms: number) => {
      setPlaying(false);
      setElapsed(Math.min(Math.max(ms, 0), totalRef.current));
    },
  };
}
