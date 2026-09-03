"use client";

import { ChevronDown, ChevronRight, Database, Search } from "lucide-react";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  formatCount,
  type RunStep,
  type TableListEntry,
  type TableListResult,
} from "~/lib/chat-run-steps";
import { CountUp, InputPills, ProgressRail, SkeletonRows } from "../card-primitives";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";
import { GenericExpanded } from "./generic-card";

/**
 * The `table_list` card (list_tables / list_databases / search_tables):
 * compact "Discovered tables · 47 tables · 3 databases"; running shows the
 * input filters with a ticking badge over ghost rows; expanded groups the
 * entries into collapsible `database.schema` sections the way the lineage
 * schema window does, with a name filter once the list grows past 15.
 */

const INPUT_KEYS = ["connection_name", "connection", "database", "schema", "pattern"] as const;
const CASCADE_CAP = 24;
const FILTER_THRESHOLD = 15;
const KEY_CHIPS = 4;
const TITLE = "Discovered tables";

function tableListResult(step: RunStep): TableListResult | null {
  return step.result?.kind === "table_list" ? step.result : null;
}

function plural(n: number, noun: string): string {
  return `${formatCount(n)} ${noun}${n === 1 ? "" : "s"}`;
}

export function summarizeTableList(step: RunStep): ToolCardSummary {
  const ok = step.status !== "failed";
  const result = tableListResult(step);
  if (!result) return { title: TITLE, stat: null, ok };
  const tables = Math.max(result.total, result.entries.length);
  if (!result.entries.length && result.databases.length) {
    const fromDbs = result.databases.reduce((sum, db) => sum + db.tableCount, 0);
    const total = tables || fromDbs;
    return {
      title: TITLE,
      stat: `${plural(result.databases.length, "database")} · ${plural(total, "table")}`,
      ok,
    };
  }
  const parts = [plural(tables, "table")];
  if (result.databases.length) parts.push(plural(result.databases.length, "database"));
  return { title: TITLE, stat: parts.join(" · "), ok };
}

/** Group key for an entry: the qualified prefix of its name, or the database. */
function groupFor(entry: TableListEntry, result: TableListResult): string {
  const dot = entry.name.lastIndexOf(".");
  const schema = dot > 0 ? entry.name.slice(0, dot) : null;
  const db = result.database;
  if (schema && db && !schema.includes(".") && schema !== db) return `${db}.${schema}`;
  return schema ?? db ?? "tables";
}

function shortName(entry: TableListEntry): string {
  const dot = entry.name.lastIndexOf(".");
  return dot > 0 ? entry.name.slice(dot + 1) : entry.name;
}

function rowCountText(entry: TableListEntry): string | null {
  if (entry.rowCountLabel) return entry.rowCountLabel;
  if (entry.rowCount != null) return formatCount(entry.rowCount);
  return null;
}

/** A badge that ticks up while the listing runs; the number re-animates. */
function TickingBadge() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setTick((value) => value + 1), 420);
    return () => window.clearInterval(id);
  }, []);
  return (
    <span
      data-testid="chat-table-list-ticker"
      className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-2 py-0.5 font-mono text-[10.5px] text-[var(--color-text-muted)]"
    >
      <span className="chat-dot-live h-1.5 w-1.5 rounded-full bg-[var(--color-success)]" />
      <span key={tick} className="chat-tool-count-tick inline-block">
        <CountUp value={tick} animate={false} />
      </span>
      <span className="text-[var(--color-text-dim)]">scanned</span>
    </span>
  );
}

export function TableListRunning({ step }: ToolCardContext) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 px-3.5 pt-3">
        <InputPills step={step} keys={INPUT_KEYS} />
        <TickingBadge />
      </div>
      <SkeletonRows columns={3} rows={3} />
      <ProgressRail label="Listing tables…" />
    </>
  );
}

function KeyChips({ entry }: { entry: TableListEntry }) {
  const keyed = entry.columns.filter((column) => column.primaryKey || column.references);
  if (!keyed.length) return null;
  const shown = keyed.slice(0, KEY_CHIPS);
  return (
    <span className="flex min-w-0 flex-wrap gap-1">
      {shown.map((column) => (
        <span
          key={column.name}
          title={column.references ? `→ ${column.references}` : "primary key"}
          className={`inline-flex items-center gap-0.5 rounded border px-1 font-mono text-[9px] ${
            column.primaryKey
              ? "chat-tool-accent-text border-[var(--chat-tool-accent)]/40"
              : "border-[var(--color-border)] text-[var(--color-text-dim)]"
          }`}
        >
          <span className="text-[8px] uppercase">{column.primaryKey ? "pk" : "fk"}</span>
          {column.name}
        </span>
      ))}
      {keyed.length > shown.length && (
        <span className="font-mono text-[9px] text-[var(--color-text-dim)]">
          +{keyed.length - shown.length}
        </span>
      )}
    </span>
  );
}

function TableRow({ entry, index }: { entry: TableListEntry; index: number }) {
  const rows = rowCountText(entry);
  const cols = entry.columns.length;
  return (
    <div
      data-testid="chat-table-list-row"
      className="chat-tool-cascade-in grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3 py-[3px] pl-7 pr-3 text-[11px] hover:bg-[var(--color-bg-hover)]/60"
      style={{ "--i": Math.min(index, CASCADE_CAP) } as CSSProperties}
    >
      <span className="flex min-w-0 items-baseline gap-2">
        <span className="truncate font-mono text-[var(--color-text)]" title={entry.name}>
          {shortName(entry)}
        </span>
        <KeyChips entry={entry} />
      </span>
      <span className="flex items-baseline gap-2 font-mono text-[10px] tabular-nums text-[var(--color-text-dim)]">
        {cols > 0 && (
          <span>
            {cols}
            {entry.columnsTruncated ? "+" : ""} col{cols === 1 ? "" : "s"}
          </span>
        )}
        {rows && (
          <span className="min-w-[3.5rem] text-right text-[var(--color-text-muted)]">
            {rows} rows
          </span>
        )}
      </span>
    </div>
  );
}

function DatabaseList({ result }: { result: TableListResult }) {
  return (
    <div data-testid="chat-table-list" className="py-1.5">
      {result.databases.map((db, index) => (
        <div
          key={db.name}
          data-testid="chat-table-list-row"
          className="chat-tool-cascade-in flex items-center gap-2 px-3.5 py-[3px] text-[11px]"
          style={{ "--i": Math.min(index, CASCADE_CAP) } as CSSProperties}
        >
          <Database className="h-3 w-3 flex-none text-[var(--color-text-dim)]" />
          <span className="truncate font-mono text-[var(--color-text)]">{db.name}</span>
          <span className="ml-auto font-mono text-[10px] tabular-nums text-[var(--color-text-muted)]">
            {plural(db.tableCount, "table")}
          </span>
        </div>
      ))}
    </div>
  );
}

type Group = { key: string; entries: TableListEntry[] };

function groupEntries(result: TableListResult): Group[] {
  const groups = new Map<string, TableListEntry[]>();
  for (const entry of result.entries) {
    const key = groupFor(entry, result);
    const list = groups.get(key);
    if (list) list.push(entry);
    else groups.set(key, [entry]);
  }
  return [...groups.entries()].map(([key, entries]) => ({ key, entries }));
}

function GroupedList({ result }: { result: TableListResult }) {
  const groups = useMemo(() => groupEntries(result), [result]);
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(
    () => new Set(groups.length > 3 ? groups.slice(1).map((group) => group.key) : []),
  );
  const q = query.trim().toLowerCase();
  const toggle = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  let rowIndex = 0;
  const hidden = Math.max(0, result.total - result.entries.length);
  const truncated = result.entriesTruncated || hidden > 0;
  return (
    <div data-testid="chat-table-list">
      {result.entries.length > FILTER_THRESHOLD && (
        <label className="flex items-center gap-2 border-b border-[var(--color-border)] px-3.5 py-1.5">
          <Search className="h-3 w-3 flex-none text-[var(--color-text-dim)]" />
          <input
            data-testid="chat-table-list-filter"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter tables"
            className="min-w-0 flex-1 bg-transparent font-mono text-[11px] text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:outline-none"
          />
        </label>
      )}
      <div className="max-h-80 overflow-auto py-1">
        {groups.map((group) => {
          const rows = q
            ? group.entries.filter((entry) => entry.name.toLowerCase().includes(q))
            : group.entries;
          if (q && !rows.length) return null;
          const isCollapsed = collapsed.has(group.key) && !q;
          return (
            <div key={group.key} data-testid="chat-table-list-group">
              <button
                type="button"
                aria-expanded={!isCollapsed}
                onClick={() => toggle(group.key)}
                className="flex w-full items-center gap-1 px-3 py-1.5 text-left text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
              >
                {isCollapsed ? (
                  <ChevronRight className="h-3 w-3 shrink-0" />
                ) : (
                  <ChevronDown className="h-3 w-3 shrink-0" />
                )}
                <span className="truncate font-mono">{group.key}</span>
                <span className="ml-auto rounded-full border border-[var(--color-border)] px-1.5 font-mono text-[9px] tabular-nums text-[var(--color-text-dim)]">
                  {rows.length}
                </span>
              </button>
              {!isCollapsed &&
                rows.map((entry) => <TableRow key={entry.name} entry={entry} index={rowIndex++} />)}
            </div>
          );
        })}
      </div>
      {truncated && (
        <div className="border-t border-[var(--color-border)] px-3.5 py-1.5 font-mono text-[10px] tabular-nums text-[var(--color-text-dim)]">
          {hidden > 0 ? `+${formatCount(hidden)} more` : "+ more tables not shown"}
        </div>
      )}
    </div>
  );
}

export function TableListExpanded(context: ToolCardContext) {
  const result = tableListResult(context.step);
  if (!result) return <GenericExpanded {...context} />;
  const header = [result.connection, result.database, result.dbType].filter(Boolean);
  return (
    <>
      {header.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-[var(--color-border)] px-3.5 py-1.5 font-mono text-[10px] text-[var(--color-text-dim)]">
          {header.map((part) => (
            <span key={part as string}>{part}</span>
          ))}
        </div>
      )}
      {!result.entries.length && result.databases.length ? (
        <DatabaseList result={result} />
      ) : (
        <GroupedList result={result} />
      )}
    </>
  );
}

registerToolCard({
  kind: "table_list",
  Icon: iconForKind("table_list"),
  accent: "schema",
  summarize: summarizeTableList,
  Running: TableListRunning,
  Expanded: TableListExpanded,
});
