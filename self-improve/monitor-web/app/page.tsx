"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import { motion } from "framer-motion";
import { clsx } from "clsx";
import Image from "next/image";
import Link from "next/link";
import type { Run, FeedEvent, RunStatus, ToolCall, SettingsStatus, RepoInfo } from "@/lib/types";
import { fetchToolCalls, fetchAuditLog, fetchAgentHealth, fetchBranches, fetchRepos, setActiveRepo, fetchRuns } from "@/lib/api";
import type { AgentHealth } from "@/lib/api";
import { fetchSettingsStatus } from "@/lib/settings-api";
import { useRuns } from "@/hooks/useRuns";
import { useSSE } from "@/hooks/useSSE";
import { useParallelRuns } from "@/hooks/useParallelRuns";
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
import { RepoSelector } from "@/components/ui/RepoSelector";
import { OnboardingModal } from "@/components/onboarding/OnboardingModal";
import { ParallelRunsView } from "@/components/parallel/ParallelRunsView";

export default function MonitorPage() {
  const [activeRepoFilter, setActiveRepoFilter] = useState<string | null>(() => {
    try { return localStorage.getItem("sp_improve_active_repo") || null; } catch { return null; }
  });
  const [repos, setRepos] = useState<RepoInfo[]>([]);
  const { runs, loading: runsLoading, refresh: refreshRuns } = useRuns(activeRepoFilter);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [historyEvents, setHistoryEvents] = useState<FeedEvent[]>([]);
  const [injectOpen, setInjectOpen] = useState(false);
  const [startModalOpen, setStartModalOpen] = useState(false);
  const [startBusy, setStartBusy] = useState(false);
  const [agentHealth, setAgentHealth] = useState<AgentHealth | null>(null);
  const [branches, setBranches] = useState<string[]>(["main"]);
  const [settingsStatus, setSettingsStatus] = useState<SettingsStatus | null>(null);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [suppressAutoSelect, setSuppressAutoSelect] = useState(false);
  const [activeView, setActiveView] = useState<"feed" | "bots">("bots");

  const {
    status: parallelStatus,
    loading: parallelBusy,
    startRun: startParallelRun,
    stopRun: parallelStop,
    killRun: parallelKill,
    pauseRun: parallelPause,
    resumeRun: parallelResume,
    unlockRun: parallelUnlock,
    injectPrompt: parallelInject,
  } = useParallelRuns();
  const parallelActive = parallelStatus?.active ?? 0;

  const { events: liveEvents, connected, clearEvents } = useSSE(selectedRunId);

  // Merge live events into history — SSE post events need to find their pre in history
  const allEvents = useMemo(() => {
    if (liveEvents.length === 0) return historyEvents;
    // Build a map of tool_use_id → index in history for quick lookups
    const preIndex = new Map<string, number>();
    const merged = [...historyEvents];
    for (let i = 0; i < merged.length; i++) {
      const ev = merged[i];
      if (ev._kind === "tool" && ev.data.phase === "pre" && !ev.data.output_data && ev.data.tool_use_id) {
        preIndex.set(ev.data.tool_use_id, i);
      }
    }
    for (const ev of liveEvents) {
      if (ev._kind === "tool" && ev.data.phase === "post" && ev.data.tool_use_id && preIndex.has(ev.data.tool_use_id)) {
        // Merge post into the matching pre in history
        const idx = preIndex.get(ev.data.tool_use_id)!;
        const pre = merged[idx];
        if (pre._kind === "tool") {
          merged[idx] = {
            _kind: "tool",
            data: { ...pre.data, output_data: ev.data.output_data, duration_ms: ev.data.duration_ms, phase: "post" },
          };
        }
        preIndex.delete(ev.data.tool_use_id);
      } else {
        merged.push(ev);
      }
    }
    return merged;
  }, [historyEvents, liveEvents]);

  const addEvent = useCallback((event: FeedEvent) => {
    setHistoryEvents((prev) => [...prev, event]);
  }, []);

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

  // Check settings status on mount and load repos
  useEffect(() => {
    fetchSettingsStatus().then((s) => {
      setSettingsStatus(s);
      if (!s.configured) setOnboardingOpen(true);
    });
    fetchRepos().then((r) => {
      setRepos(r);
      if (r.length > 0) {
        // Prefer stored repo if it still exists, otherwise pick first with runs
        const stored = activeRepoFilter;
        const valid = stored && r.some((repo) => repo.repo === stored);
        if (!valid) {
          const withRuns = r.find((repo) => repo.run_count > 0);
          const picked = withRuns?.repo || r[0].repo;
          setActiveRepoFilter(picked);
          try { localStorage.setItem("sp_improve_active_repo", picked); } catch {}
          fetchBranches(picked).then(setBranches);
        } else {
          fetchBranches(stored).then(setBranches);
        }
      }
    });
  }, []);

  // Handle repo switch — refresh everything that depends on the active repo
  // NOTE: do NOT call refreshRuns() here — it holds a stale closure with the old repo.
  // useRuns already auto-fetches when activeRepoFilter changes via its useEffect.
  const handleRepoSwitch = useCallback(async (repo: string) => {
    setSuppressAutoSelect(true);
    setActiveRepoFilter(repo || null);
    try { if (repo) localStorage.setItem("sp_improve_active_repo", repo); else localStorage.removeItem("sp_improve_active_repo"); } catch {}
    setSelectedRunId(null);
    setSelectedRun(null);
    setHistoryEvents([]);
    clearEvents();
    if (repo) {
      await setActiveRepo(repo);
      // Re-fetch branches for the new repo (direct GitHub API, no agent needed)
      fetchBranches(repo).then(setBranches);
    } else {
      setBranches(["main"]);
    }
    // Refresh repos list to get updated counts
    fetchRepos().then(setRepos);
  }, [clearEvents]);

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
      setSuppressAutoSelect(false);
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

    },
    [clearEvents]
  );

  // Auto-select first running or latest run on initial load only
  // Suppressed after repo switch so user lands on "no run selected" view
  useEffect(() => {
    if (suppressAutoSelect) return;
    if (!selectedRunId && runs.length > 0) {
      const running = runs.find((r) => r.status === "running");
      handleSelectRun(running?.id || runs[0].id);
    }
  }, [runs, selectedRunId, handleSelectRun, suppressAutoSelect]);

  // Start a new bot run (always spawns an isolated container)
  const handleStartRun = useCallback(
    async (prompt: string | undefined, budget: number, durationMinutes: number, baseBranch: string) => {
      // Close modal immediately — don't block on the API
      setStartModalOpen(false);
      const existingIds = new Set(runs.map((r) => r.id));

      // Fire API call in background
      startParallelRun(prompt, budget, durationMinutes, baseBranch).catch((err) => {
        addEvent({
          _kind: "control",
          text: `Failed to launch bot: ${err}`,
          ts: new Date().toISOString(),
        });
      });

      addEvent({
        _kind: "control",
        text: `Bot launching${prompt ? ` with custom prompt` : ""}...`,
        ts: new Date().toISOString(),
      });

      // Poll runs list until the new run appears in the sidebar
      for (let i = 0; i < 60; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        try {
          const freshRuns = await fetchRuns(activeRepoFilter || undefined);
          const newRun = freshRuns.find((r) => !existingIds.has(r.id));
          if (newRun) {
            setSuppressAutoSelect(false);
            refreshRuns();  // Update sidebar immediately
            handleSelectRun(newRun.id);
            setActiveView("feed");
            return;
          }
        } catch {}
      }
    },
    [startParallelRun, addEvent, runs, activeRepoFilter, handleSelectRun]
  );

  const runStatus: RunStatus | null =
    (selectedRun?.status as RunStatus) || null;
  const agentIdle = agentHealth?.status === "idle";
  const agentReachable = agentHealth != null && agentHealth.status !== "unreachable";
  const isConfigured = settingsStatus?.configured ?? false;

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
            {/* Logo */}
            <Image src="/logo.svg" alt="SignalPilot" width={18} height={18} className="relative z-[1]" />
          </div>
          <div>
            <h1 className="text-[12px] font-bold text-[#e8e8e8] tracking-tight">
              SignalPilot
            </h1>
            <p className="text-[9px] text-[#777] tracking-[0.1em] uppercase -mt-0.5">
              Self-Improve Monitor
            </p>
          </div>
        </div>

        {/* Repo Selector */}
        <div className="w-px h-4 bg-[#1a1a1a]" />
        <RepoSelector
          repos={repos}
          activeRepo={activeRepoFilter}
          onSelect={handleRepoSwitch}
        />

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
              {selectedRun.branch_name.replace("improvements-round-", "")}
            </span>
          </motion.div>
        )}

        <div className="flex-1" />

        {/* View toggle */}
        <div className="flex items-center gap-0.5 bg-white/[0.03] rounded p-0.5 border border-[#1a1a1a]">
          <button
            onClick={() => setActiveView("bots")}
            className={clsx(
              "px-2.5 py-1 rounded text-[10px] font-medium transition-all flex items-center gap-1.5",
              activeView === "bots"
                ? "bg-white/[0.08] text-[#e8e8e8]"
                : "text-[#666] hover:text-[#aaa]"
            )}
          >
            Bots
            {parallelActive > 0 && (
              <span className="min-w-[16px] h-[16px] flex items-center justify-center rounded-full bg-[#00ff88]/15 text-[#00ff88] text-[9px] font-bold px-1">
                {parallelActive}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveView("feed")}
            className={clsx(
              "px-2.5 py-1 rounded text-[10px] font-medium transition-all",
              activeView === "feed"
                ? "bg-white/[0.08] text-[#e8e8e8]"
                : "text-[#666] hover:text-[#aaa]"
            )}
          >
            Event Feed
          </button>
        </div>

        <div className="w-px h-4 bg-[#1a1a1a]" />

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
          <span className="text-[10px] text-[#888]">
            {!agentReachable ? "Offline" : agentIdle ? "Idle" : "Active"}
          </span>
        </div>

        {/* Settings link */}
        <Link
          href="/settings"
          className="p-1.5 rounded hover:bg-white/[0.04] text-[#888] hover:text-[#ccc] transition-colors"
          title="Settings"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </Link>

        {/* Start Run button */}
        <Button
          variant="success"
          size="md"
          onClick={() => {
            fetchBranches(activeRepoFilter || undefined).then(setBranches);
            setStartModalOpen(true);
          }}
          disabled={!isConfigured}
          title={!isConfigured ? "Configure credentials in Settings first" : undefined}
          icon={
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
              <polygon points="3 2 8 5 3 8" />
            </svg>
          }
        >
          {!isConfigured ? "Setup Required" : "New Bot"}
        </Button>

        {activeView === "feed" && selectedRunId && (
          <>
            <div className="w-px h-4 bg-[#1a1a1a]" />
            <ControlBar
              status={runStatus}
              onPause={() => parallelPause(selectedRunId)}
              onResume={() => parallelResume(selectedRunId)}
              onStop={() => parallelStop(selectedRunId)}
              onKill={() => parallelKill(selectedRunId)}
              onUnlock={() => parallelUnlock(selectedRunId)}
              onToggleInject={() => setInjectOpen(!injectOpen)}
              onResumeRun={() => parallelResume(selectedRunId)}
              busy={parallelBusy}
              sessionLocked={false}
              timeRemaining={null}
            />
          </>
        )}
      </header>

      {/* Inject Panel */}
      <InjectPanel
        open={injectOpen}
        onClose={() => setInjectOpen(false)}
        onSend={(prompt: string) => { if (selectedRunId) parallelInject(selectedRunId, prompt); }}
        busy={parallelBusy}
      />

      {/* Start Run Modal */}
      <StartRunModal
        open={startModalOpen}
        onClose={() => setStartModalOpen(false)}
        onStart={handleStartRun}
        busy={startBusy}
        branches={branches}
      />

      {/* Onboarding Modal */}
      {settingsStatus && (
        <OnboardingModal
          open={onboardingOpen}
          onComplete={() => {
            setOnboardingOpen(false);
            fetchSettingsStatus().then(setSettingsStatus);
            fetchRepos().then((r) => {
              setRepos(r);
              if (r.length > 0) {
                setActiveRepoFilter(r[0].repo);
                fetchBranches(r[0].repo).then(setBranches);
              }
            });
          }}
          initialStatus={settingsStatus}
        />
      )}

      {/* Rate Limit Banner */}
      {selectedRun?.status === "rate_limited" && selectedRun.rate_limit_resets_at && (
        <RateLimitBanner
          resetsAt={selectedRun.rate_limit_resets_at}
          onResume={() => { if (selectedRunId) parallelResume(selectedRunId); }}
          busy={parallelBusy}
        />
      )}

      {/* Main Content */}
      <div className="flex flex-1 min-h-0">
        {/* Left sidebar - Run list */}
        <RunList
          runs={runs}
          activeId={selectedRunId}
          onSelect={(id: string) => { handleSelectRun(id); setActiveView("feed"); }}
          loading={runsLoading}
        />

        {activeView === "feed" ? (
          <>
            {/* Center - Event feed */}
            <main className="flex-1 flex flex-col min-h-0 min-w-0">
              <EventFeed events={allEvents} />
              <StatsBar run={selectedRun} connected={connected} events={allEvents} />
            </main>

            {/* Right sidebar - WorkTree */}
            <WorkTree events={allEvents} runId={selectedRunId} />
          </>
        ) : (
          <main className="flex-1 flex flex-col min-h-0 min-w-0">
            <ParallelRunsView
              onStartNew={() => {
                fetchBranches(activeRepoFilter || undefined).then(setBranches);
                setStartModalOpen(true);
              }}
              branches={branches}
              label="Bots"
            />
          </main>
        )}
      </div>
    </div>
  );
}
