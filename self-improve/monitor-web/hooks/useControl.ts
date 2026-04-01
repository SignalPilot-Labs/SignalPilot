"use client";

import { useState, useCallback } from "react";
import {
  sendSignal,
  injectPrompt,
  unlockSession,
  stopAgentInstant,
  killAgent,
} from "@/lib/api";
import type { FeedEvent } from "@/lib/types";

export function useControl(
  runId: string | null,
  addEvent: (event: FeedEvent) => void
) {
  const [busy, setBusy] = useState(false);

  const exec = useCallback(
    async (action: () => Promise<unknown>, label: string) => {
      if (busy) return;
      setBusy(true);
      try {
        await action();
        addEvent({
          _kind: "control",
          text: label,
          ts: new Date().toISOString(),
        });
      } catch (err) {
        addEvent({
          _kind: "control",
          text: `Failed: ${label} — ${err}`,
          ts: new Date().toISOString(),
        });
      } finally {
        setBusy(false);
      }
    },
    [busy, addEvent]
  );

  const pause = useCallback(
    () => exec(() => sendSignal(runId!, "pause"), "Pause signal sent"),
    [exec, runId]
  );

  const resume = useCallback(
    () => exec(() => sendSignal(runId!, "resume"), "Resume signal sent"),
    [exec, runId]
  );

  // Instant stop — pushes directly to the agent's in-process queue
  const stop = useCallback(
    () => exec(() => stopAgentInstant(), "STOP sent (instant)"),
    [exec]
  );

  // Kill — immediately cancels the asyncio task, no cleanup
  const kill = useCallback(
    () => exec(() => killAgent(), "KILL sent — task cancelled immediately"),
    [exec]
  );

  const inject = useCallback(
    (prompt: string) =>
      exec(
        () => injectPrompt(runId!, prompt),
        `Prompt injected (${prompt.length} chars)`
      ),
    [exec, runId]
  );

  const unlock = useCallback(
    () =>
      exec(
        () => unlockSession(runId!),
        "Session gate unlocked — agent can now call end_session"
      ),
    [exec, runId]
  );

  return { pause, resume, stop, kill, inject, unlock, busy };
}
