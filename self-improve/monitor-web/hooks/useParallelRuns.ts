"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import type { ParallelRunSlot, ParallelStatus } from "@/lib/types";

const API = "";

const SAFE_ID = /^[\w-]+$/;

export function useParallelRuns(pollInterval = 5000) {
  const [status, setStatus] = useState<ParallelStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/parallel/status`);
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
        setError(null);
      }
    } catch {
      // Silent fail on poll
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    intervalRef.current = setInterval(fetchStatus, pollInterval);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchStatus, pollInterval]);

  const startRun = useCallback(async (
    prompt: string | undefined,
    budget: number,
    durationMinutes: number,
    baseBranch: string,
  ) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/parallel/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          max_budget_usd: budget,
          duration_minutes: durationMinutes,
          base_branch: baseBranch,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to start parallel run");
      await fetchStatus();
      return data;
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      setError(msg);
      throw e;
    } finally {
      setLoading(false);
    }
  }, [fetchStatus]);

  const sendSignal = useCallback(async (runId: string, signal: string, payload?: string) => {
    if (!SAFE_ID.test(runId) || !SAFE_ID.test(signal)) {
      setError("Invalid run ID or signal");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/parallel/runs/${runId}/${signal}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || `Failed to ${signal}`);
      }
      await fetchStatus();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [fetchStatus]);

  const stopRun = useCallback(
    (runId: string) => sendSignal(runId, "stop"),
    [sendSignal],
  );
  const killRun = useCallback(
    (runId: string) => sendSignal(runId, "kill"),
    [sendSignal],
  );
  const pauseRun = useCallback(
    (runId: string) => sendSignal(runId, "pause"),
    [sendSignal],
  );
  const resumeRun = useCallback(
    (runId: string) => sendSignal(runId, "resume"),
    [sendSignal],
  );
  const unlockRun = useCallback(
    (runId: string) => sendSignal(runId, "unlock"),
    [sendSignal],
  );
  const injectPrompt = useCallback(
    (runId: string, prompt: string) => sendSignal(runId, "inject", prompt),
    [sendSignal],
  );

  const cleanup = useCallback(async () => {
    try {
      await fetch(`${API}/api/parallel/cleanup`, { method: "POST" });
      await fetchStatus();
    } catch {
      // ignore
    }
  }, [fetchStatus]);

  return {
    status,
    loading,
    error,
    startRun,
    stopRun,
    killRun,
    pauseRun,
    resumeRun,
    unlockRun,
    injectPrompt,
    cleanup,
    refresh: fetchStatus,
  };
}
