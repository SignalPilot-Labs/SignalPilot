"use client";

import { ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { RuntimeBootState } from "~/lib/chat-run-steps";

/**
 * The sandbox boot experience, rendered ONLY on cold starts (the gateway
 * emits runtime_boot events exclusively when real provisioning or snapshot
 * resume work happens — a warm conversation never shows this).
 *
 * While booting: an animated runtime chip, the real phase, a live elapsed
 * timer, and a rotating set of true statements about the isolation model.
 * On ready: the card resolves with a completion beat and collapses into a
 * slim provenance line that stays in the transcript.
 */

const PROVISION_FACTS = [
  "Creating an isolated sandbox dedicated to this conversation",
  "Your project files are mounted read-only inside the sandbox",
  "Warehouse credentials never enter the agent's runtime",
  "Every query runs through SignalPilot's governed tools",
];

const RESUME_FACTS = [
  "Restoring the sandbox exactly where it left off",
  "Your project files and prior work are preserved",
  "Warehouse credentials never enter the agent's runtime",
];

function formatElapsed(ms: number): string {
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.floor((ms % 60_000) / 1000);
  return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
}

/** Live boots tick from the event timestamp; replays and skewed clocks
 * (baseline negative or implausibly old) fall back to time-since-mount. */
function useElapsedMs(startedAt: string, active: boolean): number {
  const [anchor] = useState(() => {
    const parsed = Date.parse(startedAt);
    const age = Date.now() - parsed;
    return Number.isFinite(parsed) && age >= 0 && age < 30 * 60_000
      ? parsed
      : Date.now();
  });
  const [elapsed, setElapsed] = useState(() => Math.max(0, Date.now() - anchor));
  useEffect(() => {
    if (!active) return;
    const tick = () => setElapsed(Math.max(0, Date.now() - anchor));
    tick();
    const interval = window.setInterval(tick, 100);
    return () => window.clearInterval(interval);
  }, [anchor, active]);
  return elapsed;
}

function BootChip({ ready }: { ready: boolean }) {
  return (
    <div className="relative h-11 w-11 flex-none" aria-hidden>
      {/* Orbit ring: sweeps while booting, solid on ready */}
      <span
        className={`absolute inset-0 rounded-xl border ${
          ready
            ? "border-[var(--color-success)]/50"
            : "border-[var(--color-border)]"
        }`}
      />
      {!ready && <span className="chat-boot-orbit absolute inset-0" />}
      <span className="absolute inset-0 flex items-center justify-center">
        {ready ? (
          <ShieldCheck className="chat-boot-check h-5 w-5 text-[var(--color-success)]" />
        ) : (
          <span className="chat-boot-core h-2.5 w-2.5 rounded-full bg-[var(--color-success)]" />
        )}
      </span>
    </div>
  );
}

export function RuntimeBootCard({ boot }: { boot: RuntimeBootState }) {
  const ready = boot.phase === "ready";
  const resuming = boot.phase === "resuming";
  const facts = resuming ? RESUME_FACTS : PROVISION_FACTS;
  const elapsedMs = useElapsedMs(boot.startedAt, !ready);
  const [factIndex, setFactIndex] = useState(0);
  // Hold the resolved card fully visible for a beat before collapsing to the
  // provenance line, so the completion lands instead of blinking away.
  const [settled, setSettled] = useState(ready);
  const settleTimer = useRef<number | null>(null);

  useEffect(() => {
    if (ready) return;
    const interval = window.setInterval(
      () => setFactIndex((index) => (index + 1) % facts.length),
      4200,
    );
    return () => window.clearInterval(interval);
  }, [ready, facts.length]);

  useEffect(() => {
    if (!ready) {
      setSettled(false);
      return;
    }
    settleTimer.current = window.setTimeout(() => setSettled(true), 1400);
    return () => {
      if (settleTimer.current) window.clearTimeout(settleTimer.current);
    };
  }, [ready]);

  const finalLabel =
    boot.bootMs != null ? formatElapsed(boot.bootMs) : formatElapsed(elapsedMs);

  if (settled) {
    return (
      <div
        data-testid="chat-runtime-boot"
        data-phase="settled"
        className="chat-step-in my-3 flex items-center gap-2 px-1 text-[11px] text-[var(--color-text-dim)]"
      >
        <ShieldCheck className="h-3.5 w-3.5 flex-none text-[var(--color-success)]/70" />
        <span>
          Secure runtime {resuming ? "restored" : "ready"}
          <span className="tabular-nums"> · {finalLabel}</span>
        </span>
      </div>
    );
  }

  return (
    <section
      data-testid="chat-runtime-boot"
      data-phase={boot.phase}
      aria-live="polite"
      className="chat-boot-in relative my-3 overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]/80"
    >
      <div className="flex items-center gap-3.5 px-4 py-3.5">
        <BootChip ready={ready} />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-[var(--color-text)]">
            {ready
              ? "Secure runtime ready"
              : resuming
                ? "Waking your workspace"
                : "Starting your secure runtime"}
          </p>
          <p
            key={ready ? "ready" : factIndex}
            className="chat-boot-fact mt-0.5 truncate text-[11px] text-[var(--color-text-muted)]"
          >
            {ready
              ? "The agent is picking up your question now."
              : facts[factIndex]}
          </p>
        </div>
        <span
          className={`flex-none text-[11px] tabular-nums ${
            ready
              ? "text-[var(--color-success)]/90"
              : "text-[var(--color-text-dim)]"
          }`}
        >
          {finalLabel}
        </span>
      </div>
      {/* Indeterminate scanner while booting; fills solid on ready */}
      <div className="h-[2px] w-full overflow-hidden bg-[var(--color-border)]/40">
        {ready ? (
          <div className="chat-boot-fill h-full bg-[var(--color-success)]/70" />
        ) : (
          <div className="chat-boot-scan h-full w-2/5 bg-gradient-to-r from-transparent via-[var(--color-success)]/70 to-transparent" />
        )}
      </div>
    </section>
  );
}
