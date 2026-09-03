"use client";

import type { CSSProperties } from "react";
import {
  formatCount,
  type ColumnProfileResult,
  type ProfiledColumn,
  type RunStep,
} from "~/lib/chat-run-steps";
import { ProgressRail, StatPill, typeDot } from "../card-primitives";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";
import { GenericExpanded } from "./generic-card";
import { tableFromInput } from "./schema-card";

/**
 * The `column_profile` card (explore_columns / explore_column /
 * profile_column): compact "Column profile · 4 columns of fct_orders";
 * running shows the requested column names as pills over ghost stat bars;
 * expanded renders one block per column with its stat pills, top-value
 * bars and sample-value chips.
 */

const BAR_CAP = 24;
const COLUMN_INPUT_KEYS = ["columns", "column", "column_names", "column_name"] as const;

function profileResult(step: RunStep): ColumnProfileResult | null {
  return step.result?.kind === "column_profile" ? step.result : null;
}

/** Column names named in the input (a string, a list, or comma-separated). */
export function columnsFromInput(step: RunStep): string[] {
  for (const key of COLUMN_INPUT_KEYS) {
    const value = step.input?.[key];
    if (Array.isArray(value)) return value.filter((v): v is string => typeof v === "string");
    if (typeof value === "string" && value) {
      return value.split(",").map((part) => part.trim()).filter(Boolean);
    }
  }
  return [];
}

/** "0.195" → "20%", "0.0000014" → "<1%", "1" → "100%". */
function formatPct(fraction: number): string {
  const pct = fraction * 100;
  if (pct > 0 && pct < 1) return "<1%";
  if (pct >= 10 || pct === 0) return `${Math.round(pct)}%`;
  return `${pct.toFixed(1)}%`;
}

/** Null share as the projector sends it (already a percentage). */
function formatNullPct(pct: number): string {
  if (pct === 0) return "0%";
  if (pct < 0.1) return "<0.1%";
  return `${pct >= 10 ? Math.round(pct) : pct.toFixed(1)}%`;
}

function singleColumnStat(column: ProfiledColumn): string {
  const parts = [column.name];
  if (column.distinctCount != null) parts.push(`${formatCount(column.distinctCount)} distinct`);
  if (column.nullPct != null) parts.push(`${formatNullPct(column.nullPct)} null`);
  return parts.join(" · ");
}

export function summarizeColumnProfile(step: RunStep): ToolCardSummary {
  const ok = step.status !== "failed";
  const result = profileResult(step);
  if (!result) return { title: "Column profile", stat: null, ok };
  if (result.columns.length === 1) {
    return { title: "Column profile", stat: singleColumnStat(result.columns[0]), ok };
  }
  const count = result.columns.length;
  const table = result.table || tableFromInput(step);
  const stat = `${formatCount(count)} column${count === 1 ? "" : "s"}${
    result.columnsTruncated ? "+" : ""
  }${table ? ` of ${table}` : ""}`;
  return { title: "Column profile", stat, ok };
}

export function ColumnProfileRunning({ step }: ToolCardContext) {
  const columns = columnsFromInput(step);
  const table = tableFromInput(step);
  return (
    <>
      <div className="flex flex-wrap items-center gap-1.5 px-3.5 pt-3">
        {table && (
          <span className="mr-1 font-mono text-[11px] text-[var(--color-text-muted)]">{table}</span>
        )}
        {columns.map((name) => (
          <span
            key={name}
            className="inline-flex items-center rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-text)]"
          >
            {name}
          </span>
        ))}
      </div>
      <div aria-hidden className="space-y-2 px-3.5 py-3">
        {[0.7, 0.45, 0.3].map((width, index) => (
          <div key={index} className="flex items-center gap-2">
            <span className="animate-shimmer h-2.5 w-16 rounded-full" />
            <span
              className="animate-shimmer h-2.5 rounded-full"
              style={{ width: `${width * 100}%`, opacity: 1 - index * 0.22 }}
            />
          </div>
        ))}
      </div>
      <ProgressRail label="Profiling columns…" />
    </>
  );
}

function TopValues({ values }: { values: ProfiledColumn["topValues"] }) {
  const max = Math.max(1, ...values.map((entry) => entry.count));
  return (
    <div data-testid="chat-column-profile-bars" className="mt-2 space-y-1">
      {values.map((entry, index) => (
        <div
          key={`${entry.value}-${index}`}
          className="grid grid-cols-[minmax(0,7rem)_1fr_auto] items-center gap-2 text-[10.5px]"
        >
          <span className="truncate font-mono text-[var(--color-text-muted)]" title={entry.value}>
            {entry.value === "" ? <span className="italic text-[var(--color-text-dim)]">empty</span> : entry.value}
          </span>
          <span className="h-1.5 overflow-hidden rounded-full bg-[var(--color-border)]/40">
            <span
              data-testid="chat-column-profile-bar"
              className="chat-tool-bar-grow block h-full rounded-full bg-[var(--chat-tool-accent)]/70"
              style={
                {
                  width: `${Math.max(1, (entry.count / max) * 100)}%`,
                  animationDelay: `${Math.min(index, BAR_CAP) * 40}ms`,
                } as CSSProperties
              }
            />
          </span>
          <span className="min-w-[3.5rem] text-right font-mono tabular-nums text-[var(--color-text-dim)]">
            {formatCount(entry.count)}
          </span>
        </div>
      ))}
    </div>
  );
}

function ColumnBlock({ column }: { column: ProfiledColumn }) {
  const nullTone =
    column.nullPct == null ? "neutral" : column.nullPct >= 10 ? "warning" : "neutral";
  return (
    <div
      data-testid="chat-column-profile-column"
      className="border-b border-[var(--color-border)] px-3.5 py-2.5 last:border-b-0"
    >
      <div className="flex min-w-0 items-center gap-2 text-[11px]">
        <span className={`h-1.5 w-1.5 flex-none rounded-full ${typeDot(column.type)}`} aria-hidden />
        <span className="truncate font-mono text-[var(--color-text)]">{column.name}</span>
        {column.type && (
          <span className="font-mono text-[10px] text-[var(--color-text-dim)]">{column.type}</span>
        )}
        {column.primaryKey && (
          <span className="chat-tool-accent-text rounded border border-[var(--chat-tool-accent)]/40 px-1 font-mono text-[9px]">
            PK
          </span>
        )}
        {column.nullable === true && (
          <span className="text-[10px] text-[var(--color-text-dim)]">nullable</span>
        )}
        {column.comment && (
          <span
            className="ml-auto min-w-0 truncate text-[10px] text-[var(--color-text-muted)]"
            title={column.comment}
          >
            {column.comment}
          </span>
        )}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {column.distinctCount != null && (
          <StatPill label="distinct" value={formatCount(column.distinctCount)} />
        )}
        {column.uniqueness != null && (
          <StatPill label="unique" value={formatPct(column.uniqueness)} />
        )}
        {column.min != null && <StatPill label="min" value={column.min} />}
        {column.max != null && <StatPill label="max" value={column.max} />}
        {column.avg != null && <StatPill label="avg" value={column.avg} />}
        {column.nullPct != null && (
          <StatPill label="null" value={formatNullPct(column.nullPct)} tone={nullTone} />
        )}
        {column.nullPct == null && column.nullCount != null && (
          <StatPill label="nulls" value={formatCount(column.nullCount)} />
        )}
      </div>
      {column.topValues.length > 0 && <TopValues values={column.topValues} />}
      {column.sampleValues.length > 0 && (
        <div
          data-testid="chat-column-profile-samples"
          className="mt-2 flex flex-wrap gap-1"
        >
          {column.sampleValues.map((value, index) => (
            <span
              key={`${value}-${index}`}
              className="max-w-[12rem] truncate rounded border border-[var(--color-border)] px-1 font-mono text-[9.5px] text-[var(--color-text-muted)]"
              title={value}
            >
              {value}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function ColumnProfileExpanded(context: ToolCardContext) {
  const result = profileResult(context.step);
  if (!result) return <GenericExpanded {...context} />;
  const meta = [
    result.table,
    result.rowCount != null && `${formatCount(result.rowCount)} rows`,
    result.filter && `where ${result.filter}`,
  ].filter((part): part is string => Boolean(part));
  return (
    <div data-testid="chat-column-profile">
      {meta.length > 0 && (
        <div className="flex flex-wrap gap-x-3 border-b border-[var(--color-border)] px-3.5 py-1.5 font-mono text-[10px] tabular-nums text-[var(--color-text-dim)]">
          {meta.map((part) => (
            <span key={part} className="truncate">
              {part}
            </span>
          ))}
        </div>
      )}
      <div className="max-h-96 overflow-auto">
        {result.columns.map((column) => (
          <ColumnBlock key={column.name} column={column} />
        ))}
      </div>
      {result.columnsTruncated && (
        <div className="border-t border-[var(--color-border)] px-3.5 py-1.5 font-mono text-[10px] text-[var(--color-text-dim)]">
          + more columns not shown
        </div>
      )}
    </div>
  );
}

registerToolCard({
  kind: "column_profile",
  Icon: iconForKind("column_profile"),
  accent: "schema",
  summarize: summarizeColumnProfile,
  Running: ColumnProfileRunning,
  Expanded: ColumnProfileExpanded,
});
