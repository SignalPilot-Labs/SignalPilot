"use client";

import { AlertTriangle, Lock } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { ChatCode, CopyButton } from "~/components/chat/chat-code";
import { useElapsedMs } from "~/components/chat/use-elapsed-ms";
import { formatCount, formatMs, toCsv, type RunStep, type TableResult } from "~/lib/chat-run-steps";
import { prettySql } from "~/lib/pretty-sql";
import { SkeletonRows } from "../card-primitives";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";
import { DataTable, type DataTableColumn } from "./data-table";
import { useFullResult } from "./use-full-result";

/**
 * The `table` card (query_database & friends). Running: the prettified SQL
 * over ghost rows with a live "Scanning the warehouse…" line. Expanded: the
 * SQL folded to three lines, the `DataTable`, and a footer with counts,
 * "Load all", completeness and PII notices, and Copy CSV. Failed and
 * legacy results render the SQL alone (`ToolCard` adds the error banner).
 *
 * "Open in Artifacts" is intentionally absent: `ConversationFileInfo` has
 * no field that references a `result_id`, so no file ↔ result link exists.
 */

const RUNNING_SQL_LINES = 6;
const EXPANDED_SQL_LINES = 3;

function tableResult(step: RunStep): TableResult | null {
  return step.result?.kind === "table" ? step.result : null;
}

function stepSql(step: RunStep): string | null {
  const fromInput = step.input?.sql;
  const raw = step.sql ?? (typeof fromInput === "string" ? fromInput : null);
  return raw && raw.trim() ? raw : null;
}

export function summarizeTable(step: RunStep): ToolCardSummary {
  const title = step.title;
  const result = tableResult(step);
  const ok = step.status !== "failed";
  if (!result) return { title, stat: null, ok };
  // No structured counts (parsed fallback, empty echo): trust the worker's
  // one-liner rather than reporting "0 rows".
  if (result.rowCount === null && result.rows.length === 0) {
    return { title, stat: ok ? result.summary : null, ok };
  }
  const rowCount = result.rowCount ?? result.rows.length;
  const parts = [`${formatCount(rowCount)} rows`];
  if (result.executionMs != null) parts.push(formatMs(result.executionMs));
  if (result.completeness !== "complete") parts.push("partial");
  return { title, stat: parts.join(" · "), ok };
}

/** Prettified SQL folded to `lines`, with a "Show all" toggle. */
export function SqlBlock({ sql, lines }: { sql: string; lines: number }) {
  const [open, setOpen] = useState(false);
  const pretty = useMemo(() => prettySql(sql), [sql]);
  const allLines = pretty.split("\n");
  const folded = !open && allLines.length > lines;
  const code = folded ? allLines.slice(0, lines).join("\n") : pretty;
  return (
    <div data-testid="chat-table-sql" className="relative">
      <ChatCode code={code} language="sql" maxHeightClass="max-h-80" />
      <div className="absolute right-1.5 top-1.5 flex items-center gap-1">
        {allLines.length > lines && (
          <button
            type="button"
            aria-expanded={!folded}
            onClick={() => setOpen((value) => !value)}
            className="rounded-md px-1.5 py-1 text-[10px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
          >
            {folded ? `Show all (${allLines.length} lines)` : "Show less"}
          </button>
        )}
        <CopyButton text={pretty} label="Copy" />
      </div>
    </div>
  );
}

export function TableRunning({ step }: ToolCardContext) {
  const sql = stepSql(step);
  const elapsed = useElapsedMs(step.startedAt, true);
  return (
    <>
      {sql && <SqlBlock sql={sql} lines={RUNNING_SQL_LINES} />}
      <div className={sql ? "border-t border-[var(--color-border)]" : ""}>
        <SkeletonRows columns={4} rows={5} />
      </div>
      <div className="flex items-center gap-2 border-t border-[var(--color-border)] px-3.5 py-2 text-[11px] text-[var(--color-text-muted)]">
        <span className="chat-dot-live h-1.5 w-1.5 flex-none rounded-full bg-[var(--color-success)]" />
        <span className="chat-live-label">Scanning the warehouse…</span>
        <span className="ml-auto font-mono text-[10px] tabular-nums text-[var(--color-text-dim)]">
          {formatMs(elapsed)}
        </span>
      </div>
    </>
  );
}

function Notice({
  tone,
  Icon,
  children,
  testId,
}: {
  tone: "warning" | "muted";
  Icon: typeof Lock;
  children: ReactNode;
  testId: string;
}) {
  const color =
    tone === "warning" ? "text-[var(--color-warning)]" : "text-[var(--color-text-muted)]";
  return (
    <div data-testid={testId} className={`flex items-start gap-1.5 text-[10.5px] leading-4 ${color}`}>
      <Icon className="mt-0.5 h-3 w-3 flex-none" />
      <span className="min-w-0 break-words">{children}</span>
    </div>
  );
}

function TableFooter({
  result,
  columns,
  rows,
  loadError,
}: {
  result: TableResult;
  columns: DataTableColumn[];
  rows: unknown[][];
  loadError: string | null;
}) {
  const rowCount = result.rowCount ?? result.rows.length;
  const stats = [`${formatCount(rowCount)} rows`];
  if (result.executionMs != null) stats.push(formatMs(result.executionMs));
  stats.push(`showing ${formatCount(rows.length)}`);
  const partial = result.completeness !== "complete";
  const csv = () => toCsv(columns.map((column) => column.name), rows);
  return (
    <div
      data-testid="chat-table-footer"
      className="space-y-1.5 border-t border-[var(--color-border)] px-3.5 py-2"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10.5px] tabular-nums text-[var(--color-text-muted)]">
          {stats.join(" · ")}
        </span>
        {result.previewTruncated && rows.length < rowCount && (
          <span className="text-[10px] text-[var(--color-text-dim)]">preview</span>
        )}
        <span className="ml-auto">
          <CopyButton text={csv()} label="Copy CSV" />
        </span>
      </div>
      {partial && (
        <Notice tone="warning" Icon={AlertTriangle} testId="chat-table-partial">
          {result.completeness === "truncated"
            ? "Result truncated by the warehouse"
            : "Result completeness unknown"}
          {result.truncationReason ? ` · ${result.truncationReason}` : ""}
        </Notice>
      )}
      {result.columnsTruncated && (
        <Notice tone="warning" Icon={AlertTriangle} testId="chat-table-columns-truncated">
          Some columns were omitted from this preview.
        </Notice>
      )}
      {result.piiRedactedColumns.length > 0 && (
        <Notice tone="muted" Icon={Lock} testId="chat-table-pii">
          Redacted:{" "}
          <span className="font-mono">{result.piiRedactedColumns.join(", ")}</span>
        </Notice>
      )}
      {loadError && (
        <Notice tone="warning" Icon={AlertTriangle} testId="chat-table-load-error">
          Could not load all rows · {loadError}
        </Notice>
      )}
    </div>
  );
}

function TableBody({
  step,
  result,
  conversationId,
}: {
  step: RunStep;
  result: TableResult;
  conversationId: string | null;
}) {
  const sql = stepSql(step);
  const rowCount = result.rowCount ?? result.rows.length;
  const full = useFullResult(conversationId, result.resultId, rowCount);
  const previewColumns = useMemo<DataTableColumn[]>(
    () => result.columns.map((column) => ({ name: column.name, type: column.logicalType })),
    [result.columns],
  );
  const ready = full.status === "ready";
  const columns = ready && full.columns.length ? full.columns : previewColumns;
  const rows = ready ? full.rows : result.rows;
  const canLoadAll = Boolean(result.resultId) && rowCount > rows.length && !ready;
  return (
    <>
      {sql && <SqlBlock sql={sql} lines={EXPANDED_SQL_LINES} />}
      <div className={sql ? "border-t border-[var(--color-border)]" : ""}>
        <DataTable
          columns={columns}
          rows={rows}
          totalRows={rowCount}
          onLoadAll={canLoadAll ? full.load : undefined}
          loadingAll={full.status === "loading"}
        />
      </div>
      <TableFooter result={result} columns={columns} rows={rows} loadError={full.error} />
    </>
  );
}

export function TableExpanded({ step, result, conversationId }: ToolCardContext) {
  const sql = stepSql(step);
  if (step.status === "failed" || result?.kind !== "table") {
    return sql ? <SqlBlock sql={sql} lines={RUNNING_SQL_LINES} /> : null;
  }
  return <TableBody step={step} result={result} conversationId={conversationId} />;
}

registerToolCard({
  kind: "table",
  Icon: iconForKind("table"),
  accent: "data",
  summarize: summarizeTable,
  Running: TableRunning,
  Expanded: TableExpanded,
  stayOpenOnComplete: (_step, isLast) => isLast,
});
