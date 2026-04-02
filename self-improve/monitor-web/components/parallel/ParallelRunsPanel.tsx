"use client";

import { useState } from "react";
import { useParallelRuns } from "@/hooks/useParallelRuns";
import type { ParallelRunSlot } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { clsx } from "clsx";

const STATUS_STYLES: Record<string, { dot: string; text: string }> = {
  starting: { dot: "bg-[#ffaa00]", text: "text-[#ffaa00]" },
  running:  { dot: "bg-[#00ff88]", text: "text-[#00ff88]" },
  completed: { dot: "bg-[#88ccff]", text: "text-[#88ccff]" },
  stopped: { dot: "bg-[#777]", text: "text-[#777]" },
  error:   { dot: "bg-[#ff4444]", text: "text-[#ff4444]" },
  killed:  { dot: "bg-[#ff4444]", text: "text-[#ff4444]" },
};

function SlotCard({ slot, onStop, onKill, onPause, onResume, onUnlock }: {
  slot: ParallelRunSlot;
  onStop: () => void;
  onKill: () => void;
  onPause: () => void;
  onResume: () => void;
  onUnlock: () => void;
}) {
  const [confirmKill, setConfirmKill] = useState(false);
  const style = STATUS_STYLES[slot.status] || STATUS_STYLES.error;
  const isActive = ["starting", "running"].includes(slot.status);
  const elapsed = slot.started_at ? Math.round((Date.now() / 1000 - slot.started_at) / 60) : 0;

  return (
    <div className="border border-[#1a1a1a] rounded-lg bg-[#0a0a0a] p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={clsx("w-2 h-2 rounded-full", style.dot, slot.status === "running" && "animate-pulse")} />
          <span className={clsx("text-[11px] font-medium uppercase tracking-wide", style.text)}>
            {slot.status}
          </span>
        </div>
        <span className="text-[10px] text-[#888] font-mono">
          {slot.container_name}
        </span>
      </div>

      {slot.prompt && (
        <p className="text-[10px] text-[#999] mb-2 line-clamp-2">
          {slot.prompt}
        </p>
      )}

      <div className="flex items-center gap-3 text-[10px] text-[#666] mb-3">
        <span>Branch: <span className="text-[#999] font-mono">{slot.base_branch}</span></span>
        <span>Elapsed: <span className="text-[#999] tabular-nums">{elapsed}m</span></span>
        {slot.max_budget_usd > 0 && (
          <span>Budget: <span className="text-[#999]">${slot.max_budget_usd}</span></span>
        )}
        {slot.duration_minutes > 0 && (
          <span>Lock: <span className="text-[#999]">{slot.duration_minutes}m</span></span>
        )}
      </div>

      {slot.error_message && (
        <p className="text-[10px] text-[#ff4444] mb-2">{slot.error_message}</p>
      )}

      {slot.run_id && (
        <p className="text-[9px] text-[#555] font-mono mb-2">Run: {slot.run_id}</p>
      )}

      {isActive && (
        <div className="flex items-center gap-1.5 pt-2 border-t border-[#1a1a1a]">
          {slot.status === "running" && (
            <Button variant="warning" onClick={onPause}>
              Pause
            </Button>
          )}
          <Button variant="danger" onClick={onStop}>
            Stop
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              if (!confirmKill) { setConfirmKill(true); setTimeout(() => setConfirmKill(false), 3000); return; }
              onKill();
              setConfirmKill(false);
            }}
            className={confirmKill ? "!bg-[#ff4444]/20 animate-pulse" : ""}
          >
            {confirmKill ? "Confirm Kill" : "Kill"}
          </Button>
          {slot.duration_minutes > 0 && (
            <Button variant="warning" onClick={onUnlock}>
              Unlock
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

export function ParallelRunsPanel({ onStartNew }: { onStartNew: () => void }) {
  const {
    status,
    stopRun,
    killRun,
    pauseRun,
    resumeRun,
    unlockRun,
    cleanup,
  } = useParallelRuns();

  const slots = status?.slots || [];
  const activeSlots = slots.filter(s => ["starting", "running"].includes(s.status));
  const finishedSlots = slots.filter(s => !["starting", "running"].includes(s.status));

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-[12px] font-semibold text-[#e8e8e8]">
            Parallel Runs
          </h3>
          <p className="text-[10px] text-[#888] mt-0.5">
            {status ? `${status.active} active / ${status.max_concurrent} max` : "Loading..."}
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

      {/* Active runs */}
      {activeSlots.length > 0 && (
        <div className="space-y-2">
          <span className="text-[10px] uppercase tracking-[0.15em] text-[#00ff88] font-semibold">
            Active ({activeSlots.length})
          </span>
          {activeSlots.map(slot => (
            <SlotCard
              key={slot.container_name}
              slot={slot}
              onStop={() => slot.run_id && stopRun(slot.run_id)}
              onKill={() => slot.run_id && killRun(slot.run_id)}
              onPause={() => slot.run_id && pauseRun(slot.run_id)}
              onResume={() => slot.run_id && resumeRun(slot.run_id)}
              onUnlock={() => slot.run_id && unlockRun(slot.run_id)}
            />
          ))}
        </div>
      )}

      {/* Finished runs */}
      {finishedSlots.length > 0 && (
        <div className="space-y-2">
          <span className="text-[10px] uppercase tracking-[0.15em] text-[#777] font-semibold">
            Finished ({finishedSlots.length})
          </span>
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
