"use client";

import { Pause, Play, RotateCcw, X } from "lucide-react";

/**
 * Control bar shown above a message while its run is being replayed.
 * Timing is "smart" compressed: 4x speed with tool waits capped at 10s.
 */
export function ReplayControls({
  elapsed,
  totalMs,
  playing,
  onTogglePlay,
  onRestart,
  onScrub,
  onExit,
}: {
  elapsed: number;
  totalMs: number;
  playing: boolean;
  onTogglePlay: () => void;
  onRestart: () => void;
  onScrub: (ms: number) => void;
  onExit: () => void;
}) {
  return (
    <div
      data-testid="chat-replay-controls"
      className="mb-3 flex items-center gap-2 rounded-xl border border-[var(--color-success)]/25 bg-[var(--color-bg-card)] px-3 py-2"
    >
      <span className="inline-flex flex-none items-center gap-1.5 rounded-full border border-[var(--color-success)]/25 bg-[var(--color-success)]/5 px-2 py-0.5 text-[10px] uppercase tracking-[0.1em] text-[var(--color-success)]">
        Replay
      </span>
      <button
        type="button"
        aria-label={playing ? "Pause replay" : "Play replay"}
        onClick={onTogglePlay}
        className="flex h-7 w-7 flex-none items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] text-[var(--color-text)] hover:border-[var(--color-border-hover)]"
      >
        {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
      </button>
      <button
        type="button"
        aria-label="Restart replay"
        onClick={onRestart}
        className="flex h-7 w-7 flex-none items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
      >
        <RotateCcw className="h-3.5 w-3.5" />
      </button>
      <input
        type="range"
        aria-label="Replay position"
        min={0}
        max={Math.max(Math.ceil(totalMs / 100) * 100, 100)}
        step={100}
        value={Math.round(Math.min(elapsed, totalMs) / 100) * 100}
        onChange={(event) => onScrub(Number(event.target.value))}
        className="h-1 min-w-24 flex-1 accent-[var(--color-success)]"
      />
      <span className="flex-none text-[11px] tabular-nums text-[var(--color-text-dim)]">
        {(elapsed / 1000).toFixed(0)}s / {(totalMs / 1000).toFixed(0)}s
      </span>
      <button
        type="button"
        aria-label="Exit replay"
        onClick={onExit}
        className="flex h-7 w-7 flex-none items-center justify-center rounded-lg text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
