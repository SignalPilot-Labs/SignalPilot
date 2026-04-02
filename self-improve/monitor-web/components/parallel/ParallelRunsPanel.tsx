"use client";

import { useCallback, useState } from "react";
import { useParallelRuns } from "@/hooks/useParallelRuns";
import { Button } from "@/components/ui/Button";
import { SlotCard } from "./SlotCard";
import type { ParallelRunSlot } from "@/lib/types";

/* ── Types ─────────────────────────────────────────────────────────── */

export interface ParallelRunsPanelProps {
  onStartNew: () => void;
  onInjectPrompt?: (runId: string, prompt: string) => void;
}

type HealthMap = Record<string, "ok" | "degraded" | "unknown">;

/* ── Summary Bar ────────────────────────────────────────────────────── */

function SummaryBar({ active, max }: { active: number; max: number }) {
  const pct = max > 0 ? Math.round((active / max) * 100) : 0;
  const barColor = active === 0 ? "bg-[#333]" : active >= max ? "bg-[#ffaa00]" : "bg-[#00ff88]";

  return (
    <div className="rounded-lg border border-[#1a1a1a] bg-[#0d0d0d] px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[9px] uppercase tracking-[0.15em] text-[#555] font-semibold">
          Capacity
        </span>
        <span className="text-[10px] text-[#888] tabular-nums">
          <span className="text-[#e8e8e8] font-medium">{active}</span>
          {" / "}
          {max}
          {" active"}
        </span>
      </div>
      <div className="h-1 rounded-full bg-[#1a1a1a] overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/* ── Section label ──────────────────────────────────────────────────── */

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[10px] uppercase tracking-[0.15em] font-semibold">
      {children}
    </span>
  );
}

/* ── Main Panel ─────────────────────────────────────────────────────── */

export function ParallelRunsPanel({ onStartNew, onInjectPrompt }: ParallelRunsPanelProps) {
  const {
    status,
    stopRun,
    killRun,
    pauseRun,
    resumeRun,
    unlockRun,
    injectPrompt,
    cleanup,
  } = useParallelRuns();

  const [healthMap, setHealthMap] = useState<HealthMap>({});

  const handleHealthCheck = useCallback(async (slot: ParallelRunSlot) => {
    if (!slot.run_id) return;
    const key = slot.run_id;
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:3401"}/api/parallel/runs/${key}/health`,
      );
      setHealthMap(prev => ({ ...prev, [key]: res.ok ? "ok" : "degraded" }));
    } catch {
      setHealthMap(prev => ({ ...prev, [key]: "degraded" }));
    }
  }, []);

  const handleInject = useCallback(
    (runId: string, prompt: string) => {
      injectPrompt(runId, prompt);
      onInjectPrompt?.(runId, prompt);
    },
    [injectPrompt, onInjectPrompt],
  );

  const slots = status?.slots ?? [];
  const activeSlots = slots.filter(s => ["starting", "running"].includes(s.status));
  const finishedSlots = slots.filter(s => !["starting", "running"].includes(s.status));

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-[12px] font-semibold text-[#e8e8e8]">Parallel Runs</h3>
          <p className="text-[10px] text-[#888] mt-0.5">
            {status ? `${status.active} active / ${status.max_concurrent} max` : "Loading…"}
          </p>
        </div>
        <div className="flex gap-1.5">
          <Button variant="success" onClick={onStartNew}>
            + New Run
          </Button>
          {finishedSlots.length > 0 && (
            <Button variant="ghost" onClick={cleanup}>
              Cleanup
            </Button>
          )}
        </div>
      </div>

      {/* Summary bar */}
      {status && (
        <SummaryBar active={status.active} max={status.max_concurrent} />
      )}

      {/* Active runs */}
      {activeSlots.length > 0 && (
        <div className="space-y-2">
          <SectionLabel>
            <span className="text-[#00ff88]">Active ({activeSlots.length})</span>
          </SectionLabel>
          {activeSlots.map(slot => (
            <SlotCard
              key={slot.container_name}
              slot={slot}
              onStop={() => slot.run_id && stopRun(slot.run_id)}
              onKill={() => slot.run_id && killRun(slot.run_id)}
              onPause={() => slot.run_id && pauseRun(slot.run_id)}
              onResume={() => slot.run_id && resumeRun(slot.run_id)}
              onUnlock={() => slot.run_id && unlockRun(slot.run_id)}
              onInject={slot.run_id ? (p) => handleInject(slot.run_id!, p) : undefined}
              onHealthCheck={() => handleHealthCheck(slot)}
              health={slot.run_id ? (healthMap[slot.run_id] ?? "unknown") : "unknown"}
            />
          ))}
        </div>
      )}

      {/* Finished runs */}
      {finishedSlots.length > 0 && (
        <div className="space-y-2">
          <SectionLabel>
            <span className="text-[#777]">Finished ({finishedSlots.length})</span>
          </SectionLabel>
          {finishedSlots.map(slot => (
            <SlotCard
              key={slot.container_name}
              slot={slot}
              onStop={() => {}}
              onKill={() => {}}
              onPause={() => {}}
              onResume={() => {}}
              onUnlock={() => {}}
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {slots.length === 0 && (
        <div className="text-center py-8">
          <p className="text-[11px] text-[#888]">No parallel runs yet</p>
          <p className="text-[10px] text-[#666] mt-1">
            Start a new run to spawn an isolated agent container
          </p>
        </div>
      )}
    </div>
  );
}
