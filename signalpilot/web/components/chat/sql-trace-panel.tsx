"use client";

import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { ChatCode } from "~/components/chat/chat-code";
import { formatByteSize } from "~/lib/chat-artifacts";
import type { SqlTraceExecution } from "~/lib/api";
import { prettySql } from "~/lib/pretty-sql";

function statusDotClass(status: string): string {
  if (status === "completed") return "bg-[var(--color-success)]";
  if (status === "failed") return "bg-[var(--color-error)]";
  if (status === "running") return "bg-[var(--color-accent)] animate-pulse";
  return "bg-[var(--color-text-dim)]";
}

function formatDuration(ms: number | null): string | null {
  if (ms === null) return null;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function DetailRow({ execution }: { execution: SqlTraceExecution }) {
  return (
    <div className="space-y-2 border-t border-[var(--color-border)] pt-2">
      {execution.sql && (
        <ChatCode
          code={prettySql(execution.sql)}
          language="sql"
          maxHeightClass="max-h-72"
        />
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 px-3.5 pb-2 text-[10px] text-[var(--color-text-dim)]">
        {execution.actual_scan_bytes !== null && (
          <span>Scanned {formatByteSize(execution.actual_scan_bytes)}</span>
        )}
        {execution.estimated_cost_usd !== null && (
          <span>Est. ${execution.estimated_cost_usd.toFixed(4)}</span>
        )}
        {execution.completeness && (
          <span>Completeness: {execution.completeness}</span>
        )}
        {execution.public_error_code && (
          <span className="text-[var(--color-error)]">
            Error: {execution.public_error_code}
          </span>
        )}
      </div>
    </div>
  );
}

function TraceRow({
  execution,
  description,
}: {
  execution: SqlTraceExecution;
  description: string | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const duration = formatDuration(execution.execution_ms);
  return (
    <li
      data-testid="sql-trace-row"
      className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)]"
    >
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)]"
      >
        <ChevronRight
          className={`h-3 w-3 flex-none transition-transform ${expanded ? "rotate-90" : ""}`}
        />
        <span
          aria-label={`Status: ${execution.status}`}
          className={`h-2 w-2 flex-none rounded-full ${statusDotClass(execution.status)}`}
        />
        {description ? (
          <span className="flex min-w-0 flex-col">
            <span
              data-testid="sql-trace-description"
              className="truncate text-[12px] text-[var(--color-text)]"
            >
              {description}
            </span>
            <span className="truncate font-mono text-[10px] text-[var(--color-text-dim)]">
              {execution.connection_name}
            </span>
          </span>
        ) : (
          <span className="truncate font-mono text-[11px] text-[var(--color-text)]">
            {execution.connection_name}
          </span>
        )}
        <span className="ml-auto flex flex-none items-center gap-3 text-[10px] text-[var(--color-text-dim)]">
          {duration && <span>{duration}</span>}
          {execution.row_count !== null && (
            <span>
              {execution.row_count.toLocaleString()}{" "}
              {execution.row_count === 1 ? "row" : "rows"}
            </span>
          )}
          {execution.actual_cost_usd !== null && (
            <span>${execution.actual_cost_usd.toFixed(4)}</span>
          )}
        </span>
      </button>
      {expanded && <DetailRow execution={execution} />}
    </li>
  );
}

/**
 * Read-only list of the conversation's governed query executions, in the
 * order the gateway returns them. `descriptions` (execution_id → the agent's
 * one-line query description, see lib/chat-query-descriptions.ts) turns the
 * bare connection name into "Comparing Q2 and Q3 revenue by region".
 */
export function SqlTracePanel({
  executions,
  descriptions,
}: {
  executions: SqlTraceExecution[];
  descriptions?: Map<string, string>;
}) {
  return (
    <div data-testid="sql-trace-panel" className="space-y-2">
      {executions.length === 0 ? (
        <p className="px-3 py-6 text-center text-xs text-[var(--color-text-dim)]">
          No queries yet.
        </p>
      ) : (
        <ul className="space-y-2">
          {executions.map((execution) => (
            <TraceRow
              key={execution.execution_id}
              execution={execution}
              description={descriptions?.get(execution.execution_id) ?? null}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
