"use client";

import { useMemo } from "react";
import type { StandaloneChatEvent, StandaloneChatRunStatus } from "~/lib/api";
import { deriveLiveState, type RunLiveInfo } from "~/lib/chat-run-steps";

/**
 * The agent's current live state (booting / thinking / tool / writing /
 * idle) for one run, recomputed only when its inputs change.
 */
export function useRunLiveState(
  events: StandaloneChatEvent[],
  runId: string | null | undefined,
  status: StandaloneChatRunStatus,
): RunLiveInfo {
  return useMemo(
    () => deriveLiveState(events, runId, status),
    [events, runId, status],
  );
}
