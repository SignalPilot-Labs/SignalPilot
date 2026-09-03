"use client";

import { AlertCircle, Check, ChevronRight, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChatCode } from "~/components/chat/chat-code";
import {
  formatStepDuration,
  type RunStep,
  type ToolResult,
} from "~/lib/chat-run-steps";
import type { ToolCardAccent, ToolCardSummary } from "./registry";

/**
 * Shared building blocks for every tool card: the frame with its header,
 * stat pills, the animated counter, the indeterminate rail, skeleton rows,
 * the raw-output toggle and the error banner. Dark, mono, restrained —
 * `--color-success` is reserved for live and success accents.
 */

/** True when the viewer asked for reduced motion (false in jsdom). */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Tailwind colour class for a column type's dot. */
export function typeDot(type: string | null | undefined): string {
  const t = (type ?? "").toLowerCase();
  if (/int|float|double|decimal|numeric|number|real|bigint|smallint/.test(t)) {
    return "bg-[#86b6de]";
  }
  if (/uuid/.test(t)) return "bg-[#e08cc7]";
  if (/bool/.test(t)) return "bg-[var(--color-warning)]";
  if (/date|time|timestamp/.test(t)) return "bg-[#b58ce0]";
  if (/json|struct|variant|map|array/.test(t)) return "bg-[#e3ae76]";
  if (/text|varchar|char|string|str/.test(t)) return "bg-[var(--color-success)]";
  return "bg-[var(--color-text-dim)]";
}

/** The kind icon in a rounded square, with the boot orbit while running. */
export function KindIcon({
  Icon,
  running,
  failed,
}: {
  Icon: LucideIcon;
  running: boolean;
  failed: boolean;
}) {
  return (
    <span className="relative h-7 w-7 flex-none" aria-hidden>
      <span
        className={`absolute inset-0 rounded-lg border bg-[var(--color-bg-input)] ${
          failed
            ? "border-[var(--color-error)]/30"
            : running
              ? "border-[var(--color-success)]/25"
              : "border-[var(--color-border)]"
        }`}
      />
      {running && <span className="chat-boot-orbit absolute inset-0 rounded-lg" />}
      <span className="absolute inset-0 flex items-center justify-center">
        <Icon
          className={`h-3.5 w-3.5 ${
            failed
              ? "text-[var(--color-error)]"
              : running
                ? "text-[var(--color-success)]"
                : "chat-tool-accent-text"
          }`}
        />
      </span>
    </span>
  );
}

/** Small labelled stat (label above, value below). */
export function StatPill({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  tone?: "neutral" | "success" | "error" | "warning";
}) {
  const toneClass =
    tone === "success"
      ? "text-[var(--color-success)]"
      : tone === "error"
        ? "text-[var(--color-error)]"
        : tone === "warning"
          ? "text-[var(--color-warning)]"
          : "text-[var(--color-text)]";
  return (
    <span className="inline-flex min-w-[64px] flex-col rounded-md border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2 py-1">
      <span className="text-[9px] uppercase tracking-[0.14em] text-[var(--color-text-dim)]">
        {label}
      </span>
      <span className={`font-mono text-[12px] tabular-nums ${toneClass}`}>{value}</span>
    </span>
  );
}

/**
 * Animated number: rAF from 0 to `value` over 600 ms (ease-out). Static
 * under reduced motion or when `animate` is false (seek-mounted cards).
 */
export function CountUp({
  value,
  animate = true,
  className,
}: {
  value: number;
  animate?: boolean;
  className?: string;
}) {
  const live = animate && !prefersReducedMotion();
  const [shown, setShown] = useState(live ? 0 : value);
  const frame = useRef<number | null>(null);
  useEffect(() => {
    if (!live) {
      setShown(value);
      return;
    }
    const start = performance.now();
    const from = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / 600);
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(Math.round(from + (value - from) * eased));
      if (t < 1) frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    };
  }, [value, live]);
  return (
    <span className={`tabular-nums ${className ?? ""}`}>
      {new Intl.NumberFormat("en-US").format(shown)}
    </span>
  );
}

/** Indeterminate scanner rail with an optional live label. */
export function ProgressRail({ label }: { label?: string }) {
  return (
    <div className="border-t border-[var(--color-border)]">
      {label && (
        <div className="flex items-center gap-2 px-3.5 py-2 text-[11px] text-[var(--color-text-muted)]">
          <span className="chat-dot-live h-1.5 w-1.5 flex-none rounded-full bg-[var(--color-success)]" />
          <span className="chat-live-label">{label}</span>
        </div>
      )}
      <div className="h-[2px] w-full overflow-hidden bg-[var(--color-border)]/40">
        <div className="chat-boot-scan h-full w-2/5 bg-gradient-to-r from-transparent via-[var(--color-success)]/70 to-transparent" />
      </div>
    </div>
  );
}

/** Ghost table rows shown while a result is on its way. */
export function SkeletonRows({
  columns = 4,
  rows = 3,
}: {
  columns?: number;
  rows?: number;
}) {
  return (
    <div aria-hidden data-testid="chat-skeleton-rows" className="space-y-1.5 px-3.5 py-3">
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="flex gap-2">
          {Array.from({ length: columns }, (_, col) => (
            <span
              key={col}
              className="animate-shimmer h-2.5 flex-1 rounded-full"
              style={{ opacity: 1 - row * 0.22 }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Selected input keys as small mono pills (connection, table, schema…). */
export function InputPills({
  step,
  keys,
}: {
  step: RunStep;
  keys: readonly string[];
}) {
  const pills = keys
    .map((key) => {
      const value = step.input?.[key];
      if (value == null || value === "") return null;
      return [key, typeof value === "string" ? value : JSON.stringify(value)] as const;
    })
    .filter((pill): pill is readonly [string, string] => pill !== null);
  if (!pills.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {pills.map(([key, value]) => (
        <span
          key={key}
          title={key}
          className="inline-flex max-w-full items-center gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-text-muted)]"
        >
          <span className="text-[var(--color-text-dim)]">{key}</span>
          <span className="truncate">{value}</span>
        </span>
      ))}
    </div>
  );
}

/** Failure headline in the error tint. */
export function ErrorBanner({ message }: { message: string | null }) {
  return (
    <div
      role="alert"
      data-testid="chat-tool-error"
      className="chat-tool-shake flex items-start gap-2 border-t border-[var(--color-error)]/25 bg-[rgba(255,68,68,0.05)] px-3.5 py-2 text-[11px] leading-4 text-[var(--color-error)]/90"
    >
      <AlertCircle className="mt-0.5 h-3 w-3 flex-none" />
      <span className="min-w-0 break-words">{message ?? "The tool returned an error."}</span>
    </div>
  );
}

function formatKb(chars: number): string {
  return `${(chars / 1024).toFixed(chars < 10 * 1024 ? 1 : 0)} KB`;
}

/** "Raw" toggle revealing the capped tool output as plain text. */
export function RawResultTab({ result }: { result: ToolResult | null }) {
  const [open, setOpen] = useState(false);
  const raw = result?.resultText;
  if (!raw) return null;
  const chars = result.resultChars ?? raw.length;
  const truncated = result.truncated || chars > raw.length;
  return (
    <div className="border-t border-[var(--color-border)]">
      <button
        type="button"
        aria-expanded={open}
        data-testid="chat-tool-raw-toggle"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-1.5 px-3.5 py-1.5 text-left text-[10px] uppercase tracking-[0.14em] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-muted)]"
      >
        <ChevronRight
          className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`}
        />
        Raw
        {truncated && (
          <span className="ml-auto normal-case tracking-normal">
            truncated to {formatKb(raw.length)} of {formatKb(chars)}
          </span>
        )}
      </button>
      {open && <ChatCode code={raw} language="text" maxHeightClass="max-h-64" />}
    </div>
  );
}

/**
 * The expanded card frame: kind icon, title, mono stat, duration, chevron.
 * `data-accent` selects the accent variable; the frame breathes while
 * running and tints red on failure.
 */
export function CardFrame({
  Icon,
  accent,
  summary,
  step,
  running,
  failed,
  open,
  onToggle,
  testId,
  children,
}: {
  Icon: LucideIcon;
  accent: ToolCardAccent;
  summary: ToolCardSummary;
  step: RunStep;
  running: boolean;
  failed: boolean;
  open: boolean;
  onToggle: () => void;
  testId?: string;
  children: ReactNode;
}) {
  const duration = formatStepDuration(step.durationMs);
  return (
    <section
      data-testid={testId}
      data-accent={accent}
      className={`overflow-hidden rounded-lg border bg-[var(--color-bg-input)] ${
        failed
          ? "border-[var(--color-error)]/30"
          : running
            ? "chat-tool-glow border-[var(--color-success)]/20"
            : "border-[var(--color-border)]"
      }`}
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex w-full items-center gap-2.5 bg-[var(--color-bg-card)] px-3 py-2 text-left hover:bg-[var(--color-bg-hover)]"
      >
        <KindIcon Icon={Icon} running={running} failed={failed} />
        <span className="flex min-w-0 flex-1 items-baseline gap-2">
          <span
            className={`truncate text-[12px] font-medium ${
              running
                ? "chat-live-label"
                : failed
                  ? "text-[var(--color-error)]"
                  : "text-[var(--color-text)]"
            }`}
          >
            {summary.title}
          </span>
          {summary.stat && (
            <span className="min-w-0 truncate font-mono text-[11px] tabular-nums text-[var(--color-text-muted)]">
              {summary.stat}
            </span>
          )}
        </span>
        <span className="ml-auto flex flex-none items-center gap-2 text-[10px] text-[var(--color-text-dim)]">
          {!running && !failed && (
            <Check className="chat-boot-check h-3 w-3 text-[var(--color-success)]/80" />
          )}
          {failed && <AlertCircle className="h-3 w-3 text-[var(--color-error)]" />}
          {duration && <span className="tabular-nums">{duration}</span>}
          <ChevronRight
            className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`}
          />
        </span>
      </button>
      <div className="chat-collapse" data-open={open}>
        <div>
          <div className="border-t border-[var(--color-border)]">{children}</div>
        </div>
      </div>
    </section>
  );
}
