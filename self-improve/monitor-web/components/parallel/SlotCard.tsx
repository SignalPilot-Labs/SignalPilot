"use client";

import { useState, useEffect, useRef } from "react";
import { clsx } from "clsx";
import { Button } from "@/components/ui/Button";
import type { ParallelRunSlot } from "@/lib/types";

const STATUS_STYLES: Record<string, { dot: string; text: string }> = {
  starting: { dot: "bg-[#ffaa00]", text: "text-[#ffaa00]" },
  running: { dot: "bg-[#00ff88]", text: "text-[#00ff88]" },
  completed: { dot: "bg-[#88ccff]", text: "text-[#88ccff]" },
  stopped: { dot: "bg-[#777]", text: "text-[#777]" },
  error: { dot: "bg-[#ff4444]", text: "text-[#ff4444]" },
  killed: { dot: "bg-[#ff4444]", text: "text-[#ff4444]" },
};

/** Elapsed minutes, re-computed on a 60-second interval without re-rendering the parent. */
function useElapsed(startedAt: number | null): number {
  const [elapsed, setElapsed] = useState(() =>
    startedAt ? Math.round((Date.now() / 1000 - startedAt) / 60) : 0,
  );

  useEffect(() => {
    if (!startedAt) return;
    const id = setInterval(() => {
      setElapsed(Math.round((Date.now() / 1000 - startedAt) / 60));
    }, 60_000);
    return () => clearInterval(id);
  }, [startedAt]);

  return elapsed;
}

export interface SlotCardProps {
  slot: ParallelRunSlot;
  onStop: () => void;
  onKill: () => void;
  onPause: () => void;
  onResume: () => void;
  onUnlock: () => void;
  onInject?: (prompt: string) => void;
  onHealthCheck?: () => void;
  health?: "ok" | "degraded" | "unknown";
}

export function SlotCard({
  slot,
  onStop,
  onKill,
  onPause,
  onResume,
  onUnlock,
  onInject,
  onHealthCheck,
  health = "unknown",
}: SlotCardProps) {
  const [confirmKill, setConfirmKill] = useState(false);
  const [showInject, setShowInject] = useState(false);
  const [injectText, setInjectText] = useState("");
  const [showDetails, setShowDetails] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const style = STATUS_STYLES[slot.status] ?? STATUS_STYLES.error;
  const isActive = ["starting", "running"].includes(slot.status);
  const elapsed = useElapsed(slot.started_at ?? null);

  const healthColor = {
    ok: "bg-[#00ff88]",
    degraded: "bg-[#ffaa00]",
    unknown: "bg-[#444]",
  }[health];

  function submitInject() {
    const trimmed = injectText.trim();
    if (!trimmed) return;
    onInject?.(trimmed);
    setInjectText("");
    setShowInject(false);
  }

  // Focus textarea when it appears
  useEffect(() => {
    if (showInject) textareaRef.current?.focus();
  }, [showInject]);

  return (
    <div className="border border-[#1a1a1a] rounded-lg bg-[#0a0a0a] p-4">
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span
            className={clsx(
              "w-2 h-2 rounded-full",
              style.dot,
              slot.status === "running" && "animate-pulse",
            )}
          />
          <span
            className={clsx(
              "text-[11px] font-medium uppercase tracking-wide",
              style.text,
            )}
          >
            {slot.status}
          </span>
          {/* Health indicator (active slots only) */}
          {isActive && (
            <button
              title={`Health: ${health}`}
              onClick={onHealthCheck}
              className="flex items-center gap-1 group"
              aria-label="Refresh health check"
            >
              <span
                className={clsx(
                  "w-1.5 h-1.5 rounded-full transition-colors",
                  healthColor,
                )}
              />
              <span className="text-[9px] text-[#555] group-hover:text-[#888] transition-colors">
                health
              </span>
            </button>
          )}
        </div>
        <span className="text-[10px] text-[#888] font-mono">
          {slot.container_name}
        </span>
      </div>

      {/* Prompt preview */}
      {slot.prompt && (
        <p className="text-[10px] text-[#999] mb-2 line-clamp-2">
          {slot.prompt}
        </p>
      )}

      {/* Meta row */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[#666] mb-3">
        <span>
          Branch:{" "}
          <span className="text-[#999] font-mono">{slot.base_branch}</span>
        </span>
        <span>
          Elapsed: <span className="text-[#999] tabular-nums">{elapsed}m</span>
        </span>
        {slot.max_budget_usd > 0 && (
          <span>
            Budget: <span className="text-[#999]">${slot.max_budget_usd}</span>
          </span>
        )}
        {slot.duration_minutes > 0 && (
          <span>
            Lock: <span className="text-[#999]">{slot.duration_minutes}m</span>
          </span>
        )}
      </div>

      {/* Error */}
      {slot.error_message && (
        <p className="text-[10px] text-[#ff4444] mb-2">{slot.error_message}</p>
      )}

      {/* Run ID */}
      {slot.run_id && (
        <p className="text-[9px] text-[#555] font-mono mb-2">
          Run: {slot.run_id}
        </p>
      )}

      {/* Collapsible detail section */}
      {(slot.volume_name || slot.container_id) && (
        <div className="mb-2">
          <button
            onClick={() => setShowDetails((v) => !v)}
            className="text-[9px] text-[#555] hover:text-[#888] transition-colors flex items-center gap-1"
          >
            <span
              className={clsx(
                "inline-block transition-transform duration-150",
                showDetails ? "rotate-90" : "rotate-0",
              )}
            >
              ▶
            </span>
            Details
          </button>
          {showDetails && (
            <div className="mt-1.5 space-y-0.5 pl-3 border-l border-[#1a1a1a]">
              {slot.volume_name && (
                <p className="text-[9px] text-[#555] font-mono">
                  Volume:{" "}
                  <span className="text-[#666]">{slot.volume_name}</span>
                </p>
              )}
              {slot.container_id && (
                <p className="text-[9px] text-[#555] font-mono">
                  Container:{" "}
                  <span className="text-[#666]">
                    {slot.container_id.slice(0, 12)}
                  </span>
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Action buttons */}
      {isActive && (
        <div className="pt-2 border-t border-[#1a1a1a] space-y-2">
          <div className="flex items-center gap-1.5 flex-wrap">
            {slot.status === "running" && (
              <Button variant="warning" onClick={onPause}>
                Pause
              </Button>
            )}
            {slot.status === "starting" && (
              <Button variant="ghost" onClick={onResume}>
                Resume
              </Button>
            )}
            <Button variant="danger" onClick={onStop}>
              Stop
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                if (!confirmKill) {
                  setConfirmKill(true);
                  setTimeout(() => setConfirmKill(false), 3000);
                  return;
                }
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
            {onInject && (
              <Button
                variant="primary"
                onClick={() => setShowInject((v) => !v)}
              >
                {showInject ? "Cancel" : "Inject"}
              </Button>
            )}
          </div>

          {/* Inline inject input */}
          {showInject && onInject && (
            <div className="space-y-1.5">
              <textarea
                ref={textareaRef}
                value={injectText}
                onChange={(e) => setInjectText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey))
                    submitInject();
                  if (e.key === "Escape") {
                    setShowInject(false);
                    setInjectText("");
                  }
                }}
                placeholder="Type a prompt to inject… (Ctrl+Enter to send)"
                rows={2}
                className={clsx(
                  "w-full rounded border border-[#1a1a1a] bg-[#0d0d0d]",
                  "text-[10px] text-[#e8e8e8] placeholder-[#555]",
                  "px-2.5 py-1.5 resize-none",
                  "focus:outline-none focus:border-[#00ff88]/40 transition-colors",
                )}
              />
              <div className="flex items-center justify-between">
                <span className="text-[9px] text-[#555]">
                  Ctrl+Enter to send · Esc to cancel
                </span>
                <Button
                  variant="success"
                  onClick={submitInject}
                  disabled={!injectText.trim()}
                >
                  Send
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
