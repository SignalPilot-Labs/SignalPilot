"use client";

/** Verdict, status, and class badges shared by the eval task and run views. */

import { type EvalCheckResult } from "~/lib/api";

const VERDICT_STYLE: Record<string, { color: string; label: string }> = {
  CORRECT: { color: "var(--color-success)", label: "correct" },
  PARTIAL: { color: "var(--color-warning, #f5a623)", label: "partial" },
  OFF: { color: "#e5484d", label: "wrong answer" },
  UNKNOWN: { color: "var(--color-warning, #f5a623)", label: "no number" },
  UNGRADED: { color: "var(--color-text-dim)", label: "ungraded" },
  ERROR: { color: "#e5484d", label: "run error" },
  SETUP_FAILED: { color: "#e5484d", label: "setup failed" },
  CANCELLED: { color: "var(--color-text-dim)", label: "cancelled" },
};

export function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) return <span className="text-xs text-[var(--color-text-dim)]">—</span>;
  const s = VERDICT_STYLE[verdict] ?? { color: "var(--color-text-dim)", label: verdict.toLowerCase() };
  return (
    <span className="text-[11px] tracking-[0.12em] uppercase whitespace-nowrap" style={{ color: s.color }}>
      {s.label}
    </span>
  );
}

export function StatusDot({ status }: { status: string }) {
  const color =
    status === "completed" ? "var(--color-success)"
    : status === "failed" ? "#e5484d"
    : status === "cancelled" ? "var(--color-text-dim)"
    : "var(--color-warning, #f5a623)";
  const live = status === "running" || status === "preparing" || status === "cancelling";
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-[0.12em]" style={{ color }}>
      <span className={`w-1.5 h-1.5 rounded-full ${live ? "animate-pulse" : ""}`} style={{ background: color }} />
      {status}
    </span>
  );
}

/** A read task runs queries. A write task builds a model on a branch. */
export function ClassBadge({ cls }: { cls: string }) {
  return <span className={`ev-badge ev-badge--${cls === "write" ? "write" : "read"}`}>{cls}</span>;
}

export function CheckChips({ results }: { results: EvalCheckResult[] }) {
  if (!results?.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      {results.map((c) => (
        <span
          key={c.name}
          className={`ev-chip ${c.passed ? "ev-chip--pass" : "ev-chip--fail"}`}
          title={
            c.detail
              ? c.detail
              : c.value != null
                ? `${c.name} = ${c.value.toLocaleString()}${c.tolerance != null ? ` ±${Math.round(c.tolerance * 100)}%` : ""}`
                : c.name
          }
        >
          <span className="n">{c.name}</span>
          {c.passed ? "✓" : "✗"}
        </span>
      ))}
    </span>
  );
}

export function shortHash(s: string | undefined | null, n = 12): string {
  return s ? s.slice(0, n) : "";
}
