"use client";

import { useState, useCallback, useEffect } from "react";
import { motion } from "framer-motion";
import type { Run, FeedEvent, RunStatus } from "@/lib/types";
import { fetchToolCalls, fetchAuditLog, startRun, fetchAgentHealth, fetchBranches } from "@/lib/api";
import type { AgentHealth } from "@/lib/api";
import { useRuns } from "@/hooks/useRuns";
import { useSSE } from "@/hooks/useSSE";
import { useControl } from "@/hooks/useControl";
import { RunList } from "@/components/sidebar/RunList";
import { EventFeed } from "@/components/feed/EventFeed";
import { ControlBar } from "@/components/controls/ControlBar";
import { InjectPanel } from "@/components/controls/InjectPanel";
import { StartRunModal } from "@/components/controls/StartRunModal";
import { StatsBar } from "@/components/stats/StatsBar";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  SignalIcon,
  RocketLaunchIcon,
} from "@heroicons/react/16/solid";

export default function MonitorPage() {
  const { runs, loading: runsLoading, refresh: refreshRuns } = useRuns();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [historyEvents, setHistoryEvents] = useState<FeedEvent[]>([]);
  const [injectOpen, setInjectOpen] = useState(false);
  const [startModalOpen, setStartModalOpen] = useState(false);
  const [startBusy, setStartBusy] = useState(false);
  const [agentHealth, setAgentHealth] = useState<AgentHealth | null>(null);
  const [branches, setBranches] = useState<string[]>(["main", "staging"]);

  const { events: liveEvents, connected, clearEvents } = useSSE(selectedRunId);
  const allEvents = [...historyEvents, ...liveEvents];

  const addEvent = useCallback((event: FeedEvent) => {
    setHistoryEvents((prev) => [...prev, event]);
  }, []);

  const { pause, resume, stop, kill, inject, unlock, busy } = useControl(
    selectedRunId,
    addEvent
  );

  // Poll agent health
  useEffect(() => {
    const check = async () => {
      const h = await fetchAgentHealth();
      setAgentHealth(h);
    };
    check();
    const id = setInterval(check, 10000);
    return () => clearInterval(id);
  }, []);

  // Auto-select first running or latest run
  useEffect(() => {
    if (!selectedRunId && runs.length > 0) {
      const running = runs.find((r) => r.status === "running");
      setSelectedRunId(running?.id || runs[0].id);
    }
  }, [runs, selectedRunId]);

  // Keep selectedRun fresh
  useEffect(() => {
    if (selectedRunId) {
      const found = runs.find((r) => r.id === selectedRunId);
      if (found) setSelectedRun(found);
    }
  }, [runs, selectedRunId]);

  // Load history when selecting a run
  const handleSelectRun = useCallback(
    async (id: string) => {
      setSelectedRunId(id);
      setHistoryEvents([]);
      clearEvents();

      try {
        const [tools, audits] = await Promise.all([
          fetchToolCalls(id, 500),
          fetchAuditLog(id, 500),
        ]);

        const toolEvents: FeedEvent[] = tools.map((t) => ({
          _kind: "tool" as const,
          data: t,
        }));

        const auditEvents: FeedEvent[] = audits
          .filter(
            (a) => !["llm_text", "llm_thinking"].includes(a.event_type)
          )
          .map((a) => ({
            _kind: "audit" as const,
            data: a,
          }));

        const merged = [...toolEvents, ...auditEvents].sort((a, b) => {
          const tsA =
            a._kind === "tool"
              ? a.data.ts
              : a._kind === "audit"
                ? a.data.ts
                : a.ts;
          const tsB =
            b._kind === "tool"
              ? b.data.ts
              : b._kind === "audit"
                ? b.data.ts
                : b.ts;
          return new Date(tsA).getTime() - new Date(tsB).getTime();
        });

        setHistoryEvents(merged);
      } catch {
        // SSE will pick up live events
      }

      refreshRuns();
    },
    [clearEvents, refreshRuns]
  );

  // Start a new run
  const handleStartRun = useCallback(
    async (prompt: string | undefined, budget: number, durationMinutes: number, baseBranch: string) => {
      setStartBusy(true);
      try {
        const result = await startRun(prompt, budget, durationMinutes, baseBranch);
        setStartModalOpen(false);
        addEvent({
          _kind: "control",
          text: `New run started${prompt ? ` with custom prompt` : ""}`,
          ts: new Date().toISOString(),
        });
        // Wait a moment then refresh to pick up the new run
        setTimeout(async () => {
          await refreshRuns();
          if (result.run_id) {
            setSelectedRunId(result.run_id);
            handleSelectRun(result.run_id);
          }
        }, 2000);
      } catch (err) {
        addEvent({
          _kind: "control",
          text: `Failed to start run: ${err}`,
          ts: new Date().toISOString(),
        });
      } finally {
        setStartBusy(false);
      }
    },
    [addEvent, refreshRuns, handleSelectRun]
  );

  const runStatus: RunStatus | null =
    (selectedRun?.status as RunStatus) || null;
  const agentIdle = agentHealth?.status === "idle";
  const agentReachable = agentHealth != null && agentHealth.status !== "unreachable";

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <header className="relative z-10 flex items-center gap-4 px-5 py-3 border-b border-white/[0.06] bg-[#0a0d12] header-glow">
        <div className="flex items-center gap-2.5">
          <div className="flex items-center justify-center h-7 w-7 rounded-lg bg-sky-500/10 border border-sky-500/20">
            <SignalIcon className="h-3.5 w-3.5 text-sky-400" />
          </div>
          <div>
            <h1 className="text-[13px] font-bold text-zinc-200 tracking-tight">
              SignalPilot
            </h1>
            <p className="text-[9px] text-zinc-600 -mt-0.5">
              Self-Improve Monitor
            </p>
          </div>
        </div>

        {selectedRun && (
          <motion.div
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex items-center gap-3 ml-2"
          >
            <div className="w-px h-5 bg-white/[0.06]" />
            <StatusBadge
              status={selectedRun.status as RunStatus}
              size="md"
            />
            <span className="text-[11px] text-sky-400 font-medium">
              {selectedRun.branch_name}
            </span>
          </motion.div>
        )}

        <div className="flex-1" />

        {/* Start Run button */}
        <Button
          variant="success"
          size="md"
          onClick={() => { fetchBranches().then(setBranches); setStartModalOpen(true); }}
          disabled={!agentIdle || !agentReachable}
          icon={<RocketLaunchIcon className="h-3.5 w-3.5" />}
        >
          {!agentReachable
            ? "Agent Offline"
            : !agentIdle
              ? "Run In Progress"
              : "New Run"}
        </Button>

        <div className="w-px h-5 bg-white/[0.06]" />

        <ControlBar
          status={runStatus}
          onPause={pause}
          onResume={resume}
          onStop={stop}
          onKill={kill}
          onUnlock={unlock}
          onToggleInject={() => setInjectOpen(!injectOpen)}
          busy={busy}
          sessionLocked={agentHealth?.session_unlocked === false}
          timeRemaining={agentHealth?.time_remaining || null}
        />
      </header>

      {/* Inject Panel */}
      <InjectPanel
        open={injectOpen}
        onClose={() => setInjectOpen(false)}
        onSend={inject}
        busy={busy}
      />

      {/* Start Run Modal */}
      <StartRunModal
        open={startModalOpen}
        onClose={() => setStartModalOpen(false)}
        onStart={handleStartRun}
        busy={startBusy}
        branches={branches}
      />

      {/* Main */}
      <div className="flex flex-1 min-h-0">
        <RunList
          runs={runs}
          activeId={selectedRunId}
          onSelect={handleSelectRun}
          loading={runsLoading}
        />

        <main className="flex-1 flex flex-col min-h-0 min-w-0">
          <EventFeed events={allEvents} />
          <StatsBar run={selectedRun} connected={connected} />
        </main>
      </div>
    </div>
  );
}
