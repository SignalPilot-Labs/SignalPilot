"use client";

import { useState, useCallback, useEffect } from "react";
import { motion } from "framer-motion";
import type { Run, FeedEvent, RunStatus, ToolCall } from "@/lib/types";
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
import { RateLimitBanner } from "@/components/controls/RateLimitBanner";
import { WorkTree } from "@/components/worktree/WorkTree";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

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

  const { pause, resume, stop, kill, inject, unlock, resumeSession, busy } = useControl(
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

        // API returns DESC order — sort ASC so pre comes before post
        tools.sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
        audits.sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());

        // Merge pre/post tool call pairs.
        // Pre has input_data (no output), post has output_data (no input).
        // Use tool_use_id when available (new runs), fall back to name-based
        // matching for historical data without tool_use_id.
        const mergedTools: ToolCall[] = [];

        for (const t of tools) {
          if (t.phase === "pre") {
            mergedTools.push({ ...t });
          } else {
            // phase === "post": find matching pre and merge
            let matched = false;

            // Strategy 1: Match by tool_use_id (exact, handles parallel calls)
            if (t.tool_use_id) {
              for (let j = mergedTools.length - 1; j >= 0; j--) {
                const pre = mergedTools[j];
                if (pre.tool_use_id === t.tool_use_id && pre.phase === "pre") {
                  pre.output_data = t.output_data;
                  pre.duration_ms = t.duration_ms;
                  pre.phase = "post";
                  matched = true;
                  break;
                }
              }
            }

            // Strategy 2: Fall back to name-based matching (old data)
            if (!matched) {
              for (let j = mergedTools.length - 1; j >= 0; j--) {
                const pre = mergedTools[j];
                if (
                  pre.tool_name === t.tool_name &&
                  pre.phase === "pre" &&
                  !pre.output_data
                ) {
                  pre.output_data = t.output_data;
                  pre.duration_ms = t.duration_ms;
                  pre.phase = "post";
                  matched = true;
                  break;
                }
              }
            }

            if (!matched) {
              mergedTools.push({ ...t });
            }
          }
        }

        const toolEvents: FeedEvent[] = mergedTools.map((t) => ({
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

        const getTs = (e: FeedEvent): string =>
          e._kind === "tool" ? e.data.ts
          : e._kind === "audit" ? e.data.ts
          : e._kind === "usage" ? e.data.ts
          : e.ts;
        const merged = [...toolEvents, ...auditEvents].sort((a, b) =>
          new Date(getTs(a)).getTime() - new Date(getTs(b)).getTime()
        );

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
    <div className="h-screen flex flex-col bg-[var(--color-bg)]">
      {/* Header */}
      <header className="relative z-10 flex items-center gap-3 px-4 py-2.5 border-b border-[#1a1a1a] bg-[#0a0a0a] header-glow">
        {/* Logo */}
        <div className="flex items-center gap-2">
          <div className="relative flex items-center justify-center h-7 w-7">
            {/* Animated status ring */}
            <svg width="28" height="28" viewBox="0 0 28 28" className="absolute">
              <circle
                cx="14" cy="14" r="12"
                fill="none"
                stroke={runStatus === "running" ? "rgba(0,255,136,0.2)" : "rgba(255,255,255,0.06)"}
                strokeWidth="1"
                strokeDasharray="4 3"
                style={runStatus === "running" ? { animation: "spin 8s linear infinite" } : undefined}
              />
            </svg>
            {/* Logo icon */}
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={runStatus === "running" ? "#00ff88" : "#555"} strokeWidth="1.5" strokeLinecap="round">
              <path d="M2 10L5 4L7 7L9 3L12 10" />
            </svg>
          </div>
          <div>
            <h1 className="text-[12px] font-bold text-[#e8e8e8] tracking-tight">
              SignalPilot
            </h1>
            <p className="text-[8px] text-[#444] tracking-[0.1em] uppercase -mt-0.5">
              Self-Improve Monitor
            </p>
          </div>
        </div>

        {selectedRun && (
          <motion.div
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex items-center gap-2.5 ml-1"
          >
            <div className="w-px h-4 bg-[#1a1a1a]" />
            <StatusBadge
              status={selectedRun.status as RunStatus}
              size="md"
            />
            <span className="text-[10px] text-[#888] font-medium">
              {selectedRun.name || selectedRun.branch_name.replace("improvements-round-", "")}
            </span>
          </motion.div>
        )}

        <div className="flex-1" />

        {/* About link */}
        <a
          href="/landing"
          className="text-[9px] text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)] transition-colors tracking-[0.15em] uppercase mr-2"
        >
          About
        </a>

        {/* Agent health indicator */}
        <div className="flex items-center gap-1.5 mr-2">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              agentReachable
                ? agentIdle
                  ? "bg-[#00ff88]/60"
                  : "bg-[#00ff88]"
                : "bg-[#ff4444]/60"
            }`}
            style={!agentIdle && agentReachable ? { boxShadow: "0 0 4px rgba(0,255,136,0.3)" } : undefined}
          />
          <span className="text-[8px] text-[#555]">
            {!agentReachable ? "Offline" : agentIdle ? "Idle" : "Active"}
          </span>
        </div>

        {/* Start Run button */}
        <Button
          variant="success"
          size="md"
          onClick={() => { fetchBranches().then(setBranches); setStartModalOpen(true); }}
          disabled={!agentIdle || !agentReachable}
          icon={
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
              <polygon points="3 2 8 5 3 8" />
            </svg>
          }
        >
          {!agentReachable
            ? "Offline"
            : !agentIdle
              ? "Running"
              : "New Run"}
        </Button>

        <div className="w-px h-4 bg-[#1a1a1a]" />

        <ControlBar
          status={runStatus}
          onPause={pause}
          onResume={resume}
          onStop={stop}
          onKill={kill}
          onUnlock={unlock}
          onToggleInject={() => setInjectOpen(!injectOpen)}
          onResumeRun={resumeSession}
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

      {/* Rate Limit Banner */}
      {selectedRun?.status === "rate_limited" && selectedRun.rate_limit_resets_at && (
        <RateLimitBanner
          resetsAt={selectedRun.rate_limit_resets_at}
          onResume={resumeSession}
          busy={busy}
        />
      )}

      {/* Main Content */}
      <div className="flex flex-1 min-h-0">
        {/* Left sidebar - Run list */}
        <RunList
          runs={runs}
          activeId={selectedRunId}
          onSelect={handleSelectRun}
          loading={runsLoading}
        />

        {/* Center - Event feed */}
        <main className="flex-1 flex flex-col min-h-0 min-w-0">
          <EventFeed events={allEvents} />
          <StatsBar run={selectedRun} connected={connected} />
        </main>

        {/* Right sidebar - WorkTree */}
        <WorkTree events={allEvents} runId={selectedRunId} />
      </div>
    </div>
  );
}
