"use client";

import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { ChatCode } from "~/components/chat/chat-code";
import type { DbtRunResult, RunStep } from "~/lib/chat-run-steps";
import { ProgressRail, StatPill } from "../card-primitives";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";

/**
 * dbt run card: `dbt_execute` / `refresh_mart`. Pass / warn / error / skip
 * tallies, a stacked proportion bar, the failing nodes first, and the log
 * tail folded underneath. Cards with errors stay open after completion.
 */

export type DbtTally = { pass: number; warn: number; error: number; skip: number };

const BUCKET_FOR_STATUS: Record<string, keyof DbtTally> = {
  success: "pass",
  pass: "pass",
  ok: "pass",
  warn: "warn",
  warning: "warn",
  error: "error",
  fail: "error",
  failed: "error",
  "runtime error": "error",
  skip: "skip",
  skipped: "skip",
};

function dbtResult(step: RunStep): DbtRunResult | null {
  return step.result?.kind === "dbt_run" ? step.result : null;
}

/** Folds the projector's status map into the four displayed buckets. */
export function tallyStatuses(statuses: Record<string, number>): DbtTally {
  const tally: DbtTally = { pass: 0, warn: 0, error: 0, skip: 0 };
  for (const [status, count] of Object.entries(statuses)) {
    const bucket = BUCKET_FOR_STATUS[status.toLowerCase()];
    if (bucket && Number.isFinite(count)) tally[bucket] += count;
  }
  return tally;
}

function commandWord(step: RunStep, result: DbtRunResult | null): string {
  const raw = result?.command ?? (typeof step.input?.command === "string" ? step.input.command : "");
  const word = raw.trim().replace(/^dbt\s+/, "").split(/\s+/)[0] ?? "";
  return word || "run";
}

function selectArg(step: RunStep): string | null {
  const raw = step.input?.select ?? step.input?.models;
  if (typeof raw === "string" && raw.trim()) return raw.trim();
  if (Array.isArray(raw) && raw.length) return raw.map(String).join(" ");
  return null;
}

function formatElapsed(seconds: number): string {
  return seconds >= 60
    ? `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`
    : `${seconds.toFixed(1)} s`;
}

export function summarizeDbtRun(step: RunStep): ToolCardSummary {
  const result = dbtResult(step);
  const title = `dbt ${commandWord(step, result)}`;
  const failed = step.status === "failed";
  if (!result) return { title, stat: null, ok: !failed };
  const tally = tallyStatuses(result.statuses);
  const hasStatuses = Object.keys(result.statuses).length > 0;
  const parts: string[] = [];
  if (hasStatuses) {
    parts.push(`${tally.pass} ✓ ${tally.error} ✗`);
    if (tally.warn > 0) parts.push(`${tally.warn} ⚠`);
    if (tally.skip > 0) parts.push(`${tally.skip} skip`);
  } else if (result.exitCode != null) {
    parts.push(`exit ${result.exitCode}`);
  }
  if (result.elapsedS != null) parts.push(formatElapsed(result.elapsedS));
  const exitOk = result.exitCode === 0 || result.exitCode === null;
  return {
    title,
    stat: parts.length ? parts.join(" · ") : null,
    ok: !failed && tally.error === 0 && exitOk,
  };
}

function CommandLine({ step, result }: { step: RunStep; result: DbtRunResult | null }) {
  const select = selectArg(step);
  const command = result?.command?.trim() || `dbt ${commandWord(step, null)}`;
  const full = select && !command.includes("--select") ? `${command} --select ${select}` : command;
  return (
    <div className="px-3.5 py-2.5 font-mono text-[11.5px] text-[var(--color-text)]">
      <span className="mr-1.5 text-[var(--color-text-dim)]">$</span>
      {full.startsWith("dbt") ? full : `dbt ${full}`}
    </div>
  );
}

export function DbtRunRunning({ step }: ToolCardContext) {
  const progress = step.detail?.trim();
  return (
    <div data-testid="chat-dbt-run-card">
      <CommandLine step={step} result={null} />
      <ProgressRail label={progress || "Running dbt…"} />
    </div>
  );
}

const SEGMENTS: { key: keyof DbtTally; label: string; tone: "success" | "warning" | "error" | "neutral"; color: string }[] = [
  { key: "pass", label: "Pass", tone: "success", color: "bg-[var(--color-success)]/80" },
  { key: "warn", label: "Warn", tone: "warning", color: "bg-[var(--color-warning)]/80" },
  { key: "error", label: "Error", tone: "error", color: "bg-[var(--color-error)]/85" },
  { key: "skip", label: "Skip", tone: "neutral", color: "bg-[var(--color-text-dim)]/50" },
];

function Tallies({ tally }: { tally: DbtTally }) {
  const total = tally.pass + tally.warn + tally.error + tally.skip;
  return (
    <div className="px-3.5 py-3">
      <div className="flex flex-wrap gap-1.5" data-testid="chat-dbt-run-tallies">
        {SEGMENTS.map(({ key, label, tone }) => (
          <StatPill
            key={key}
            label={label}
            value={tally[key]}
            tone={tally[key] > 0 ? tone : "neutral"}
          />
        ))}
      </div>
      {total > 0 && (
        <div
          aria-hidden
          className="mt-2.5 flex h-1.5 w-full gap-px overflow-hidden rounded-full bg-[var(--color-border)]/40"
        >
          {SEGMENTS.filter(({ key }) => tally[key] > 0).map(({ key, color }) => (
            <span
              key={key}
              className={`chat-tool-bar-grow h-full ${color}`}
              style={{ width: `${(tally[key] / total) * 100}%` }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function Failures({ failures }: { failures: DbtRunResult["failures"] }) {
  // Errors first: anything that reads like a warning drops to the bottom.
  const ordered = [...failures].sort(
    (a, b) => Number(/warn/i.test(a.message)) - Number(/warn/i.test(b.message)),
  );
  return (
    <ul data-testid="chat-dbt-run-failures" className="border-t border-[var(--color-border)]">
      {ordered.map((failure, index) => (
        <li
          key={`${failure.node}-${index}`}
          className="border-l-2 border-[var(--color-error)]/60 bg-[rgba(255,68,68,0.04)] px-3.5 py-2"
        >
          <div className="font-mono text-[11px] text-[var(--color-text)]">{failure.node}</div>
          <div className="mt-0.5 break-words text-[11px] leading-4 text-[var(--color-error)]/90">
            {failure.message}
          </div>
        </li>
      ))}
    </ul>
  );
}

function LogTail({ result, defaultOpen }: { result: DbtRunResult; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  if (!result.log) return null;
  return (
    <div className="border-t border-[var(--color-border)]">
      <button
        type="button"
        aria-expanded={open}
        data-testid="chat-dbt-run-log-toggle"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-1.5 px-3.5 py-1.5 text-left text-[10px] uppercase tracking-[0.14em] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-muted)]"
      >
        <ChevronRight className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`} />
        Log
        {result.logTruncated && (
          <span className="ml-auto normal-case tracking-normal">tail only</span>
        )}
      </button>
      {open && <ChatCode code={result.log} language="text" maxHeightClass="max-h-64" />}
    </div>
  );
}

export function DbtRunExpanded({ step }: ToolCardContext) {
  const result = dbtResult(step);
  if (!result) {
    // Legacy completion: only the command is known.
    return (
      <div data-testid="chat-dbt-run-card">
        <CommandLine step={step} result={null} />
      </div>
    );
  }
  const tally = tallyStatuses(result.statuses);
  const meta = [
    result.targetSchema && `target ${result.targetSchema}`,
    result.sync && `sync ${result.sync}`,
    result.exitCode != null && `exit ${result.exitCode}`,
  ].filter((part): part is string => Boolean(part));
  return (
    <div data-testid="chat-dbt-run-card">
      <CommandLine step={step} result={result} />
      <div className="border-t border-[var(--color-border)]">
        <Tallies tally={tally} />
      </div>
      {result.failures.length > 0 && <Failures failures={result.failures} />}
      {meta.length > 0 && (
        <div className="border-t border-[var(--color-border)] px-3.5 py-1.5 font-mono text-[10.5px] text-[var(--color-text-dim)]">
          {meta.join(" · ")}
        </div>
      )}
      <LogTail result={result} defaultOpen={tally.error > 0} />
    </div>
  );
}

registerToolCard({
  kind: "dbt_run",
  Icon: iconForKind("dbt_run"),
  accent: "dbt",
  summarize: summarizeDbtRun,
  Running: DbtRunRunning,
  Expanded: DbtRunExpanded,
  stayOpenOnComplete: (step) => {
    const result = dbtResult(step);
    return result ? tallyStatuses(result.statuses).error > 0 : false;
  },
});
