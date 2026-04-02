"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  Play,
  Database,
  Loader2,
  Clock,
  Table2,
  AlertTriangle,
  ChevronDown,
  Download,
  Copy,
  Check,
  XCircle,
  Shield,
  DollarSign,
  Zap,
  BookOpen,
} from "lucide-react";
import { executeQuery as apiExecuteQuery, getConnectionSchemaLink } from "@/lib/api";
import { useConnection } from "@/lib/connection-context";
import { EmptyQuery, EmptyState } from "@/components/ui/empty-states";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";
import { SqlHighlight } from "@/components/ui/sql-highlight";
import { Tooltip } from "@/components/ui/tooltip";

/* ── Column type detection from values ── */
const typeColorMap: Record<string, string> = {
  number: "text-blue-400",
  string: "text-green-400",
  boolean: "text-yellow-400",
  null: "text-[var(--color-text-dim)]",
  object: "text-orange-400",
};

function inferColumnType(rows: Record<string, unknown>[], col: string): { type: string; color: string; dot: string } {
  for (const row of rows.slice(0, 10)) {
    const val = row[col];
    if (val == null) continue;
    if (typeof val === "boolean") return { type: "bool", color: typeColorMap.boolean, dot: "bg-yellow-400" };
    if (typeof val === "number") return { type: Number.isInteger(val) ? "int" : "float", color: typeColorMap.number, dot: "bg-blue-400" };
    if (typeof val === "object") return { type: "json", color: typeColorMap.object, dot: "bg-orange-400" };
    const s = String(val);
    if (/^\d{4}-\d{2}-\d{2}/.test(s)) return { type: "time", color: "text-purple-400", dot: "bg-purple-400" };
    if (/^[0-9a-f]{8}-[0-9a-f]{4}/.test(s)) return { type: "uuid", color: "text-pink-400", dot: "bg-pink-400" };
    return { type: "text", color: typeColorMap.string, dot: "bg-green-400" };
  }
  return { type: "null", color: typeColorMap.null, dot: "bg-[var(--color-text-dim)]" };
}

interface QueryResult {
  rows: Record<string, unknown>[];
  row_count: number;
  tables: string[];
  execution_ms: number;
  sql_executed: string;
  cache_hit?: boolean;
  cost_estimate?: {
    estimated_rows: number;
    estimated_usd: number;
    is_expensive: boolean;
  };
  pii_redacted?: string[];
}

const HISTORY_KEY = "sp_query_history";

/* ── Query templates per DB type ── */
const QUERY_TEMPLATES: Record<string, { label: string; sql: string }[]> = {
  postgres: [
    { label: "List tables", sql: "SELECT table_schema, table_name\nFROM information_schema.tables\nWHERE table_schema NOT IN ('pg_catalog', 'information_schema')\nORDER BY table_schema, table_name;" },
    { label: "Table sizes", sql: "SELECT\n  schemaname || '.' || tablename AS table,\n  pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) AS total_size,\n  pg_size_pretty(pg_relation_size(schemaname || '.' || tablename)) AS data_size\nFROM pg_tables\nWHERE schemaname NOT IN ('pg_catalog', 'information_schema')\nORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC\nLIMIT 20;" },
    { label: "Running queries", sql: "SELECT pid, now() - pg_stat_activity.query_start AS duration,\n  query, state\nFROM pg_stat_activity\nWHERE (now() - pg_stat_activity.query_start) > interval '5 seconds'\n  AND state != 'idle'\nORDER BY duration DESC;" },
    { label: "Index usage", sql: "SELECT\n  schemaname || '.' || relname AS table,\n  indexrelname AS index,\n  idx_scan AS scans,\n  pg_size_pretty(pg_relation_size(indexrelid)) AS size\nFROM pg_stat_user_indexes\nORDER BY idx_scan DESC\nLIMIT 20;" },
  ],
  mysql: [
    { label: "List tables", sql: "SELECT table_schema, table_name, table_rows,\n  ROUND(data_length / 1024 / 1024, 2) AS data_mb\nFROM information_schema.tables\nWHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')\nORDER BY table_rows DESC;" },
    { label: "Table sizes", sql: "SELECT table_schema, table_name,\n  ROUND((data_length + index_length) / 1024 / 1024, 2) AS total_mb\nFROM information_schema.tables\nWHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')\nORDER BY (data_length + index_length) DESC\nLIMIT 20;" },
    { label: "Show processlist", sql: "SELECT id, user, host, db, command, time, state,\n  LEFT(info, 100) AS query\nFROM information_schema.processlist\nWHERE command != 'Sleep'\nORDER BY time DESC;" },
  ],
  snowflake: [
    { label: "List schemas", sql: "SHOW SCHEMAS;" },
    { label: "List tables", sql: "SELECT table_schema, table_name, row_count,\n  bytes / 1024 / 1024 AS size_mb\nFROM information_schema.tables\nWHERE table_schema NOT IN ('INFORMATION_SCHEMA')\nORDER BY row_count DESC NULLS LAST;" },
    { label: "Warehouse usage", sql: "SELECT warehouse_name, \n  SUM(credits_used) AS total_credits,\n  COUNT(*) AS query_count\nFROM snowflake.account_usage.warehouse_metering_history\nWHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())\nGROUP BY warehouse_name\nORDER BY total_credits DESC;" },
    { label: "Query history", sql: "SELECT query_id, query_text, database_name,\n  execution_status, total_elapsed_time / 1000 AS elapsed_sec\nFROM snowflake.account_usage.query_history\nWHERE start_time >= DATEADD('hour', -24, CURRENT_TIMESTAMP())\nORDER BY start_time DESC\nLIMIT 20;" },
  ],
  bigquery: [
    { label: "List datasets", sql: "SELECT schema_name\nFROM INFORMATION_SCHEMA.SCHEMATA;" },
    { label: "List tables", sql: "SELECT table_schema, table_name, table_type,\n  row_count, ROUND(size_bytes / 1024 / 1024 / 1024, 2) AS size_gb\nFROM `region-us`.INFORMATION_SCHEMA.TABLE_STORAGE\nORDER BY size_bytes DESC\nLIMIT 20;" },
    { label: "Job history", sql: "SELECT job_id, user_email, query,\n  total_bytes_processed / 1024 / 1024 / 1024 AS gb_processed,\n  total_slot_ms / 1000 AS slot_sec\nFROM `region-us`.INFORMATION_SCHEMA.JOBS\nWHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)\nORDER BY total_bytes_processed DESC\nLIMIT 20;" },
  ],
  clickhouse: [
    { label: "List tables", sql: "SELECT database, name, engine,\n  formatReadableSize(total_bytes) AS size,\n  total_rows\nFROM system.tables\nWHERE database NOT IN ('system', 'INFORMATION_SCHEMA', 'information_schema')\nORDER BY total_bytes DESC;" },
    { label: "Running queries", sql: "SELECT query_id, user, elapsed,\n  formatReadableSize(memory_usage) AS memory,\n  LEFT(query, 100) AS query\nFROM system.processes\nWHERE is_initial_query = 1\nORDER BY elapsed DESC;" },
    { label: "Part sizes", sql: "SELECT database, table,\n  COUNT() AS parts,\n  formatReadableSize(SUM(bytes_on_disk)) AS size,\n  SUM(rows) AS total_rows\nFROM system.parts\nWHERE active AND database NOT IN ('system')\nGROUP BY database, table\nORDER BY SUM(bytes_on_disk) DESC\nLIMIT 20;" },
  ],
  redshift: [
    { label: "List tables", sql: "SELECT schemaname, tablename, \n  \"column\" AS dist_key, diststyle\nFROM pg_table_def\nJOIN svv_table_info ON tablename = \"table\"\nWHERE schemaname NOT IN ('pg_catalog', 'information_schema')\nLIMIT 20;" },
    { label: "Table sizes", sql: "SELECT \"schema\" || '.' || \"table\" AS table_name,\n  size AS size_mb, tbl_rows\nFROM svv_table_info\nORDER BY size DESC\nLIMIT 20;" },
    { label: "Running queries", sql: "SELECT pid, user_name, starttime,\n  DATEDIFF('second', starttime, GETDATE()) AS elapsed_sec,\n  LEFT(querytxt, 100) AS query\nFROM stv_recents\nWHERE status = 'Running'\nORDER BY starttime;" },
  ],
  databricks: [
    { label: "List schemas", sql: "SHOW SCHEMAS;" },
    { label: "List tables", sql: "SELECT table_schema, table_name, table_type\nFROM information_schema.tables\nWHERE table_schema NOT IN ('information_schema')\nORDER BY table_schema, table_name;" },
    { label: "Describe table", sql: "DESCRIBE TABLE EXTENDED your_schema.your_table;" },
  ],
  trino: [
    { label: "List catalogs", sql: "SHOW CATALOGS;" },
    { label: "List schemas", sql: "SHOW SCHEMAS;" },
    { label: "List tables", sql: "SHOW TABLES;" },
    { label: "Running queries", sql: "SELECT query_id, state, query,\n  date_diff('second', created, now()) AS elapsed_sec\nFROM system.runtime.queries\nWHERE state = 'RUNNING'\nORDER BY created;" },
  ],
  mssql: [
    { label: "List tables", sql: "SELECT s.name AS [schema], t.name AS [table],\n  p.rows AS row_count\nFROM sys.tables t\nJOIN sys.schemas s ON t.schema_id = s.schema_id\nLEFT JOIN sys.partitions p ON t.object_id = p.object_id AND p.index_id IN (0, 1)\nWHERE s.name NOT IN ('sys')\nORDER BY p.rows DESC;" },
    { label: "Table sizes", sql: "SELECT s.name + '.' + t.name AS [table],\n  SUM(a.total_pages) * 8 / 1024 AS total_mb,\n  SUM(a.used_pages) * 8 / 1024 AS used_mb,\n  p.rows\nFROM sys.tables t\nJOIN sys.schemas s ON t.schema_id = s.schema_id\nJOIN sys.indexes i ON t.object_id = i.object_id\nJOIN sys.partitions p ON i.object_id = p.object_id AND i.index_id = p.index_id\nJOIN sys.allocation_units a ON p.partition_id = a.container_id\nGROUP BY s.name, t.name, p.rows\nORDER BY SUM(a.total_pages) DESC;" },
    { label: "Running queries", sql: "SELECT r.session_id, r.status, r.command,\n  r.cpu_time, r.total_elapsed_time / 1000 AS elapsed_sec,\n  LEFT(t.text, 100) AS query\nFROM sys.dm_exec_requests r\nCROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t\nWHERE r.status != 'background'\nORDER BY r.total_elapsed_time DESC;" },
  ],
  duckdb: [
    { label: "List tables", sql: "SELECT table_schema, table_name\nFROM information_schema.tables\nORDER BY table_schema, table_name;" },
    { label: "System info", sql: "SELECT * FROM duckdb_settings()\nWHERE name IN ('threads', 'memory_limit', 'max_memory');" },
  ],
  sqlite: [
    { label: "List tables", sql: "SELECT name, type FROM sqlite_master\nWHERE type IN ('table', 'view')\nORDER BY name;" },
    { label: "Table info", sql: "SELECT m.name AS table_name, p.*\nFROM sqlite_master m\nJOIN pragma_table_info(m.name) p\nWHERE m.type = 'table'\nORDER BY m.name, p.cid;" },
  ],
};

export default function QueryExplorerPage() {
  const { toast } = useToast();
  const { connections, selectedConn, setSelectedConn } = useConnection();
  const [sql, setSql] = useState<string>("");
  const [rowLimit, setRowLimit] = useState<number>(1000);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorHint, setErrorHint] = useState<string | null>(null);
  const [history, setHistory] = useState<
    { sql: string; connection: string; ts: number; duration_ms: number; row_count?: number; cache_hit?: boolean }[]
  >([]);
  const [copied, setCopied] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  const [schemaContext, setSchemaContext] = useState<string>("");
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [showSchema, setShowSchema] = useState(false);
  const [schemaLinked, setSchemaLinked] = useState(0);
  const [schemaTotal, setSchemaTotal] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const lineNumbersRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(HISTORY_KEY);
      if (stored) setHistory(JSON.parse(stored));
    } catch {}
  }, []);

  const runQuery = useCallback(async () => {
    if (!sql.trim() || !selectedConn) return;
    setExecuting(true);
    setError(null);
    setErrorHint(null);
    setResult(null);

    try {
      const data = await apiExecuteQuery(selectedConn, sql.trim(), rowLimit);
      setResult(data as QueryResult);
      const newHistory = [
        {
          sql: sql.trim(),
          connection: selectedConn,
          ts: Date.now(),
          duration_ms: data.execution_ms,
          row_count: data.row_count,
          cache_hit: (data as Record<string, unknown>).cache_hit as boolean | undefined,
        },
        ...history.filter((h) => h.sql !== sql.trim()).slice(0, 49),
      ];
      setHistory(newHistory);
      try { localStorage.setItem(HISTORY_KEY, JSON.stringify(newHistory)); } catch {}
    } catch (e) {
      const msg = String(e instanceof Error ? e.message : e);
      // Parse structured error with hint from gateway
      try {
        const jsonMatch = msg.match(/\d+:\s*(\{.*\})\s*$/);
        if (jsonMatch) {
          const parsed = JSON.parse(jsonMatch[1]);
          if (parsed.detail?.error) {
            setError(parsed.detail.error);
            setErrorHint(parsed.detail.hint || null);
          } else if (parsed.error) {
            setError(parsed.error);
            setErrorHint(parsed.hint || null);
          } else {
            setError(msg);
          }
        } else {
          setError(msg);
        }
      } catch {
        setError(msg);
      }
    } finally {
      setExecuting(false);
    }
  }, [sql, selectedConn, rowLimit, history]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      runQuery();
    }
  }

  // Sync line numbers scroll with textarea
  function handleScroll() {
    if (lineNumbersRef.current && textareaRef.current) {
      lineNumbersRef.current.scrollTop = textareaRef.current.scrollTop;
    }
  }

  const lineCount = Math.max(sql.split("\n").length, 6);

  async function loadSchemaContext() {
    if (!selectedConn || !sql.trim()) return;
    setSchemaLoading(true);
    setShowSchema(true);
    try {
      const data = await getConnectionSchemaLink(selectedConn, sql.trim(), "ddl", 10);
      setSchemaContext(data.ddl || data.schema || "-- No relevant tables found");
      setSchemaLinked(data.linked_tables);
      setSchemaTotal(data.total_tables);
    } catch (e) {
      setSchemaContext(`-- Error loading schema: ${e}`);
    } finally {
      setSchemaLoading(false);
    }
  }

  function exportCSV() {
    if (!result || result.rows.length === 0) return;
    const columns = Object.keys(result.rows[0]);
    const csvLines = [columns.join(",")];
    for (const row of result.rows) {
      csvLines.push(
        columns
          .map((c) => {
            const val = row[c];
            const str = val == null ? "" : String(val);
            return str.includes(",") || str.includes('"') || str.includes("\n")
              ? `"${str.replace(/"/g, '""')}"`
              : str;
          })
          .join(",")
      );
    }
    const blob = new Blob([csvLines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `query-${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function exportJSON() {
    if (!result || result.rows.length === 0) return;
    const blob = new Blob([JSON.stringify(result.rows, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `query-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function copyResults() {
    if (!result || result.rows.length === 0) return;
    const columns = Object.keys(result.rows[0]);
    const lines = [columns.join("\t")];
    for (const row of result.rows) {
      lines.push(columns.map((c) => String(row[c] ?? "")).join("\t"));
    }
    navigator.clipboard.writeText(lines.join("\n"));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    toast(`${result.rows.length} rows copied to clipboard`, "success");
  }

  return (
    <div className="p-4 sm:p-8 flex flex-col min-h-screen sm:h-screen sm:max-h-screen animate-fade-in">
      <div className="flex-shrink-0">
        <PageHeader
          title="query"
          subtitle="explorer"
          description="governed, read-only sql queries"
          actions={
            <div className="flex items-center gap-2 px-3 py-1.5 border border-[var(--color-success)]/20 bg-[var(--color-success)]/5">
              <Shield className="w-3 h-3 text-[var(--color-success)]" strokeWidth={1.5} />
              <span className="text-[12px] text-[var(--color-success)] tracking-wider">
                read-only / ddl blocked / limit enforced
              </span>
            </div>
          }
        />
      </div>

      <TerminalBar
        path={`query ${selectedConn || "—"} --governed --read-only`}
        status={<StatusDot status={selectedConn ? "healthy" : "unknown"} size={4} pulse={executing} />}
      >
        <div className="flex items-center gap-3 sm:gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">history: <code className="text-[12px] text-[var(--color-text)]">{history.length}</code></span>
          {result && <span className="text-[var(--color-success)]">rows: <code className="text-[12px]">{result.row_count}</code></span>}
        </div>
      </TerminalBar>

      {/* Connection bar + controls */}
      <div className="flex flex-wrap items-center gap-3 mb-4 flex-shrink-0">
        <div className="relative flex-1 min-w-[120px] sm:min-w-[160px] sm:flex-none">
          <select
            value={selectedConn}
            onChange={(e) => setSelectedConn(e.target.value)}
            className="appearance-none w-full sm:w-auto pl-3 pr-8 py-2.5 sm:py-2 bg-[var(--color-bg-card)] border border-[var(--color-border)] text-base sm:text-xs focus:outline-none focus:border-[var(--color-text-dim)] sm:min-w-[200px] tracking-wide"
          >
            {connections.length === 0 ? (
              <option value="">no connections</option>
            ) : (
              connections.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name} ({c.db_type})
                </option>
              ))
            )}
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-[var(--color-text-dim)] pointer-events-none" />
        </div>

        <div className="flex items-center gap-1.5 px-2 py-1 border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          <label className="text-[12px] text-[var(--color-text-dim)] tracking-wider">limit:</label>
          <input
            type="number"
            value={rowLimit}
            onChange={(e) =>
              setRowLimit(Math.max(1, Math.min(100000, Number(e.target.value) || 1000)))
            }
            className="w-16 px-1 py-1 bg-transparent text-base sm:text-xs text-center focus:outline-none tabular-nums"
          />
        </div>

        {/* Query templates dropdown */}
        <div className="relative">
          <button
            onClick={() => setShowTemplates(!showTemplates)}
            disabled={!selectedConn}
            className="flex items-center gap-1.5 px-2.5 py-2 border border-[var(--color-border)] text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-all tracking-wider disabled:opacity-30"
          >
            <BookOpen className="w-3 h-3" strokeWidth={1.5} />
            templates
            <ChevronDown className="w-2.5 h-2.5" />
          </button>
          {showTemplates && selectedConn && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowTemplates(false)} />
              <div className="absolute left-0 top-full mt-1 z-50 min-w-[200px] border border-[var(--color-border)] bg-[var(--color-bg-card)] shadow-lg">
                {(() => {
                  const conn = connections.find(c => c.name === selectedConn);
                  const templates = conn ? QUERY_TEMPLATES[conn.db_type] || [] : [];
                  if (templates.length === 0) return (
                    <div className="px-3 py-2 text-[12px] text-[var(--color-text-dim)] tracking-wider">no templates for this db type</div>
                  );
                  return templates.map((t, i) => (
                    <button
                      key={i}
                      onClick={() => { setSql(t.sql); setShowTemplates(false); }}
                      className="w-full text-left px-3 py-2 text-[12px] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] transition-colors tracking-wider border-b border-[var(--color-border)] last:border-b-0"
                    >
                      {t.label}
                    </button>
                  ));
                })()}
              </div>
            </>
          )}
        </div>

        <div className="hidden sm:block flex-1" />

        <Tooltip content="Show relevant tables for your query (schema linking)" position="bottom">
          <button
            onClick={loadSchemaContext}
            disabled={schemaLoading || !sql.trim() || !selectedConn}
            className="flex items-center gap-1.5 px-3 py-2 border border-[var(--color-border)] text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-all tracking-wider disabled:opacity-30"
          >
            {schemaLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Table2 className="w-3 h-3" strokeWidth={1.5} />}
            schema
            {schemaLinked > 0 && <span className="text-[11px] px-1 py-0.5 border border-blue-500/20 text-blue-400 tabular-nums">{schemaLinked}</span>}
          </button>
        </Tooltip>

        <button
          onClick={runQuery}
          disabled={executing || !sql.trim() || !selectedConn}
          className="flex items-center justify-center gap-2 w-full sm:w-auto px-5 py-3 sm:py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
        >
          {executing ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Play className="w-3.5 h-3.5" />
          )}
          execute
          <kbd className="ml-1 px-1.5 py-0.5 bg-[var(--color-bg)]/20 text-[10px] opacity-60 border border-[var(--color-bg)]/30 hidden sm:inline">
            ctrl+⏎
          </kbd>
        </button>
      </div>

      {/* Mobile SQL keyword toolbar */}
      <div className="sm:hidden flex items-center gap-1.5 mb-2 overflow-x-auto flex-shrink-0 -mx-1 px-1 [-webkit-overflow-scrolling:touch]">
        {["SELECT", "FROM", "WHERE", "JOIN", "GROUP BY", "ORDER BY", "LIMIT", "AND", "OR", "AS", "ON", "LEFT", "COUNT(*)", "DISTINCT", "*"].map((kw) => (
          <button
            key={kw}
            onClick={() => {
              const ta = textareaRef.current;
              if (!ta) return;
              const start = ta.selectionStart;
              const before = sql.slice(0, start);
              const after = sql.slice(ta.selectionEnd);
              const insert = (before.length > 0 && !before.endsWith(" ") && !before.endsWith("\n") ? " " : "") + kw + " ";
              setSql(before + insert + after);
              // Restore cursor position after insert
              requestAnimationFrame(() => {
                ta.focus();
                const pos = start + insert.length;
                ta.setSelectionRange(pos, pos);
              });
            }}
            className="flex-shrink-0 px-2.5 py-1.5 text-[10px] text-[var(--color-text-dim)] bg-[var(--color-bg-card)] border border-[var(--color-border)] active:bg-[var(--color-bg-hover)] active:text-[var(--color-text)] tracking-wider font-mono whitespace-nowrap"
          >
            {kw}
          </button>
        ))}
      </div>

      {/* SQL editor with line numbers */}
      <div className="relative mb-4 flex-shrink-0 border border-[var(--color-border)] bg-[var(--color-bg-card)] flex overflow-hidden card-radial-glow">
        {/* Line numbers gutter */}
        <div
          ref={lineNumbersRef}
          className="flex-shrink-0 py-3 pr-0 pl-2 sm:pl-3 select-none overflow-hidden border-r border-[var(--color-border)] bg-[var(--color-bg)] w-8 sm:w-12"
        >
          {Array.from({ length: lineCount }, (_, i) => (
            <div key={i} className="text-[12px] text-[var(--color-text-dim)] text-right pr-2 leading-[1.65rem] tabular-nums opacity-50">
              {i + 1}
            </div>
          ))}
        </div>
        {/* Editor */}
        <textarea
          ref={textareaRef}
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          onKeyDown={handleKeyDown}
          onScroll={handleScroll}
          placeholder="SELECT * FROM users LIMIT 10;"
          rows={6}
          spellCheck={false}
          className="flex-1 px-4 py-3 bg-transparent text-base sm:text-xs font-mono focus:outline-none resize-y placeholder:text-[var(--color-text-dim)] leading-[1.65rem] tracking-wide"
        />
        {/* Bottom info bar */}
        <div className="absolute bottom-0 right-0 flex items-center gap-3 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] bg-[var(--color-bg-card)]">
          {sql.length > 0 && (
            <span className="tabular-nums">{sql.length} chars</span>
          )}
          <span className="tracking-wider opacity-60 hidden sm:inline">ctrl+enter</span>
        </div>
      </div>

      {/* Schema context panel */}
      {showSchema && (
        <div className="mb-4 border border-[var(--color-border)] bg-[var(--color-bg-card)] flex-shrink-0 animate-fade-in">
          <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-border)]">
            <div className="flex items-center gap-2">
              <Table2 className="w-3 h-3 text-blue-400" strokeWidth={1.5} />
              <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider uppercase">
                relevant schema
              </span>
              {schemaLinked > 0 && (
                <span className="text-[11px] text-[var(--color-text-dim)] tabular-nums">
                  {schemaLinked}/{schemaTotal} tables linked
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => navigator.clipboard.writeText(schemaContext)}
                className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
              >
                copy
              </button>
              <button
                onClick={() => setShowSchema(false)}
                className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
              >
                close
              </button>
            </div>
          </div>
          {schemaLoading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-dim)]" />
            </div>
          ) : (
            <pre className="px-4 py-3 text-[12px] text-[var(--color-text-muted)] overflow-x-auto font-mono leading-relaxed max-h-[200px] overflow-y-auto whitespace-pre">
              {schemaContext}
            </pre>
          )}
        </div>
      )}

      {/* Error display */}
      {error && (
        <div className="mb-4 flex items-start gap-3 p-4 border border-[var(--color-error)]/30 bg-[var(--color-error)]/5 flex-shrink-0 animate-fade-in">
          <XCircle className="w-3.5 h-3.5 text-[var(--color-error)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
          <div>
            <p className="text-xs text-[var(--color-error)] mb-1 tracking-wider">query error</p>
            <p className="text-[12px] text-[var(--color-text-muted)]">{error}</p>
            {errorHint && (
              <div className="mt-2 flex items-start gap-2 px-3 py-2 bg-[var(--color-warning)]/10 border border-[var(--color-warning)]/20">
                <Zap className="w-3 h-3 text-[var(--color-warning)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
                <p className="text-[12px] text-[var(--color-warning)]">{errorHint}</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="flex-1 flex flex-col min-h-0 border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden animate-fade-in">
          {/* Result header */}
          <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 border-b border-[var(--color-border)] flex-shrink-0">
            <div className="flex flex-wrap items-center gap-3 sm:gap-4">
              <span className="flex items-center gap-1.5 text-[12px] text-[var(--color-success)] tracking-wider">
                <Table2 className="w-3 h-3" strokeWidth={1.5} />
                {result.row_count.toLocaleString()} row{result.row_count !== 1 ? "s" : ""}
              </span>
              <span className="flex items-center gap-1.5 text-[12px] text-[var(--color-text-dim)] tracking-wider">
                <Clock className="w-3 h-3" strokeWidth={1.5} />
                {result.execution_ms.toFixed(0)}ms
              </span>
              {result.tables.length > 0 && (
                <span className="flex items-center gap-1.5 text-[12px] text-[var(--color-text-dim)] tracking-wider">
                  <Database className="w-3 h-3" strokeWidth={1.5} />
                  {result.tables.join(", ")}
                </span>
              )}
              {result.cache_hit && (
                <span className="flex items-center gap-1 text-[11px] px-1.5 py-0.5 border badge-success tracking-wider uppercase">
                  <Zap className="w-2.5 h-2.5" /> cached
                </span>
              )}
              {result.cost_estimate && (
                <span className={`flex items-center gap-1 text-[11px] px-1.5 py-0.5 border tracking-wider ${
                  result.cost_estimate.is_expensive ? "badge-error" : "border-[var(--color-border)] text-[var(--color-text-dim)]"
                }`}>
                  <DollarSign className="w-2.5 h-2.5" />
                  ~${result.cost_estimate.estimated_usd.toFixed(6)}
                </span>
              )}
              {result.pii_redacted && result.pii_redacted.length > 0 && (
                <span className="flex items-center gap-1 text-[11px] px-1.5 py-0.5 border badge-warning tracking-wider uppercase">
                  <Shield className="w-2.5 h-2.5" /> pii redacted ({result.pii_redacted.length})
                </span>
              )}
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={copyResults}
                className="flex items-center gap-1.5 px-2.5 py-2 sm:py-1 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider active:text-[var(--color-text)]"
              >
                {copied ? <Check className="w-3 h-3 text-[var(--color-success)]" /> : <Copy className="w-3 h-3" />}
                {copied ? "copied" : "copy"}
              </button>
              <button
                onClick={exportCSV}
                className="flex items-center gap-1.5 px-2.5 py-2 sm:py-1 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider active:text-[var(--color-text)]"
              >
                <Download className="w-3 h-3" /> csv
              </button>
              <button
                onClick={exportJSON}
                className="flex items-center gap-1.5 px-2.5 py-2 sm:py-1 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider active:text-[var(--color-text)]"
              >
                <Download className="w-3 h-3" /> json
              </button>
            </div>
          </div>

          {/* Result table */}
          <div className="flex-1 overflow-auto">
            {result.rows.length === 0 ? (
              <div className="flex items-center justify-center py-12 text-xs text-[var(--color-text-dim)]">
                query returned 0 rows
              </div>
            ) : (
              <>
                {/* Mobile card view */}
                <div className="sm:hidden divide-y divide-[var(--color-border)]/30">
                  {result.rows.map((row, i) => (
                    <div key={i} className="px-3 py-3">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[11px] text-[var(--color-text-dim)] tabular-nums tracking-wider">row {i + 1}</span>
                        <button
                          onClick={() => {
                            const text = Object.entries(row).map(([k, v]) => `${k}: ${v ?? "null"}`).join("\n");
                            navigator.clipboard.writeText(text).then(() => {
                              toast(`row ${i + 1} copied`, "info");
                            }).catch(() => {});
                          }}
                          className="text-[11px] text-[var(--color-text-dim)] tracking-wider flex items-center gap-1 p-1.5 -m-1.5 active:text-[var(--color-text)]"
                        >
                          <Copy className="w-3 h-3" /> copy
                        </button>
                      </div>
                      <div className="space-y-1.5">
                        {Object.entries(row).map(([col, val], j) => {
                          const colType = inferColumnType(result.rows, col);
                          return (
                            <div key={j} className="flex items-start gap-2">
                              <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider min-w-[80px] max-w-[100px] truncate flex-shrink-0 pt-0.5 flex items-center gap-1">
                                <span className={`w-1 h-1 flex-shrink-0 ${colType.dot}`} />
                                {col}
                                {result.pii_redacted?.includes(col) && (
                                  <Shield className="w-2 h-2 text-[var(--color-warning)] flex-shrink-0" />
                                )}
                              </span>
                              <span
                                className="text-[11px] text-[var(--color-text-muted)] break-all flex-1 min-w-0"
                                onClick={() => {
                                  if (val != null) {
                                    navigator.clipboard.writeText(String(val)).then(() => {
                                      toast(`copied: ${String(val).slice(0, 50)}`, "info");
                                    }).catch(() => {});
                                  }
                                }}
                              >
                                {val == null ? (
                                  <span className="text-[var(--color-text-dim)] italic opacity-50">null</span>
                                ) : typeof val === "number" ? (
                                  <span className="tabular-nums text-[var(--color-text)]">{val.toLocaleString()}</span>
                                ) : typeof val === "boolean" ? (
                                  <span className={`font-medium ${val ? "text-[var(--color-success)]" : "text-[var(--color-error)]"}`}>
                                    {String(val)}
                                  </span>
                                ) : typeof val === "object" ? (
                                  <span className="text-orange-400/80 font-mono text-[12px]">{JSON.stringify(val).slice(0, 80)}</span>
                                ) : /^\d{4}-\d{2}-\d{2}/.test(String(val)) ? (
                                  <span className="text-purple-400/80 tabular-nums">{String(val)}</span>
                                ) : /^[0-9a-f]{8}-[0-9a-f]{4}/.test(String(val)) ? (
                                  <span className="text-pink-400/70 font-mono text-[12px]">{String(val)}</span>
                                ) : (
                                  String(val)
                                )}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Desktop table view */}
                <table className="hidden sm:table w-full text-[12px] table-fixed-header">
                  <thead className="sticky top-0 bg-[var(--color-bg-card)]">
                    <tr className="border-b border-[var(--color-border)]">
                      <th className="px-3 py-2 text-left text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] w-10">
                        #
                      </th>
                      {Object.keys(result.rows[0]).map((col) => {
                        const colType = inferColumnType(result.rows, col);
                        return (
                          <th
                            key={col}
                            className="px-3 py-2 text-left text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]"
                          >
                            <Tooltip content={`${colType.type}${result.pii_redacted?.includes(col) ? " · pii redacted" : ""}`} position="top">
                              <span className="inline-flex items-center gap-1.5 cursor-default">
                                <span className={`w-1 h-1 flex-shrink-0 ${colType.dot}`} />
                                {col}
                                {result.pii_redacted?.includes(col) && (
                                  <Shield className="w-2.5 h-2.5 text-[var(--color-warning)]" />
                                )}
                              </span>
                            </Tooltip>
                          </th>
                        );
                      })}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--color-border)]/30">
                    {result.rows.map((row, i) => (
                      <tr key={i} className="table-row-hover">
                        <td className="px-3 py-1.5 text-[var(--color-text-dim)] tabular-nums text-[11px]">{i + 1}</td>
                        {Object.entries(row).map(([col, val], j) => (
                          <td
                            key={j}
                            className="px-3 py-1.5 text-[var(--color-text-muted)] max-w-[300px] truncate cursor-default group/cell relative"
                            title={val == null ? "NULL" : String(val)}
                            onClick={() => {
                              if (val != null) {
                                navigator.clipboard.writeText(String(val)).then(() => {
                                  toast(`copied: ${String(val).slice(0, 50)}`, "info");
                                }).catch(() => {});
                              }
                            }}
                          >
                            {val == null ? (
                              <span className="text-[var(--color-text-dim)] italic opacity-50">null</span>
                            ) : typeof val === "number" ? (
                              <span className="tabular-nums text-[var(--color-text)]">{val.toLocaleString()}</span>
                            ) : typeof val === "boolean" ? (
                              <span className={`font-medium ${val ? "text-[var(--color-success)]" : "text-[var(--color-error)]"}`}>
                                {String(val)}
                              </span>
                            ) : typeof val === "object" ? (
                              <span className="text-orange-400/80 font-mono text-[12px]">{JSON.stringify(val).slice(0, 60)}</span>
                            ) : /^\d{4}-\d{2}-\d{2}/.test(String(val)) ? (
                              <span className="text-purple-400/80 tabular-nums">{String(val)}</span>
                            ) : /^[0-9a-f]{8}-[0-9a-f]{4}/.test(String(val)) ? (
                              <span className="text-pink-400/70 font-mono text-[12px]">{String(val)}</span>
                            ) : (
                              String(val)
                            )}
                            {/* Click-to-copy hint */}
                            <span className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover/cell:opacity-100 transition-opacity text-[10px] text-[var(--color-text-dim)]">
                              <Copy className="w-2.5 h-2.5" />
                            </span>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          {/* SQL executed footer */}
          {result.sql_executed !== sql.trim() && (
            <div className="px-4 py-2 border-t border-[var(--color-border)] flex-shrink-0">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-3 h-3 text-[var(--color-warning)]" strokeWidth={1.5} />
                <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider">
                  governed sql (limit injected):
                </span>
                <span className="text-[12px] truncate">
                  <SqlHighlight sql={result.sql_executed} className="text-[12px]" />
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Query history */}
      {history.length > 0 && !result && !error && (
        <div className="mt-4 border border-[var(--color-border)] bg-[var(--color-bg-card)] animate-fade-in">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--color-border)]">
            <div className="flex items-center gap-2">
              <Clock className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
              <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                history ({history.length})
              </span>
            </div>
            <div className="flex items-center gap-3">
              {history.length >= 3 && (
                <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider tabular-nums">
                  avg: {Math.round(history.reduce((s, h) => s + h.duration_ms, 0) / history.length)}ms
                </span>
              )}
              <button
                onClick={() => { setHistory([]); localStorage.removeItem(HISTORY_KEY); }}
                className="text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-error)] transition-colors tracking-wider"
              >
                clear
              </button>
            </div>
          </div>
          <div className="divide-y divide-[var(--color-border)]/30 max-h-72 overflow-auto stagger-fade-in">
            {history.map((h, i) => (
              <button
                key={i}
                onClick={() => {
                  setSql(h.sql);
                  setSelectedConn(h.connection);
                }}
                className="w-full text-left px-4 py-3.5 sm:py-2.5 hover:bg-[var(--color-bg-hover)] active:bg-[var(--color-bg-hover)] transition-colors group flex items-start gap-3"
              >
                <span className="text-[11px] text-[var(--color-text-dim)] tabular-nums w-5 text-right flex-shrink-0 mt-0.5 opacity-40 select-none">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] block truncate overflow-hidden">
                    <SqlHighlight sql={h.sql.slice(0, 100)} className="text-[13px]" />
                  </div>
                  <div className="flex items-center gap-3 mt-1 text-[11px] text-[var(--color-text-dim)] tracking-wider">
                    <span className="flex items-center gap-1">
                      <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
                        <ellipse cx="4" cy="3" rx="3" ry="1.5" stroke="currentColor" strokeWidth="0.75" fill="none" />
                        <path d="M1 3V5.5C1 6.3 2.3 7 4 7C5.7 7 7 6.3 7 5.5V3" stroke="currentColor" strokeWidth="0.75" />
                      </svg>
                      {h.connection}
                    </span>
                    <span className={`tabular-nums ${h.duration_ms < 100 ? "text-[var(--color-success)]" : h.duration_ms < 500 ? "text-[var(--color-text-dim)]" : "text-[var(--color-warning)]"}`}>
                      {h.duration_ms.toFixed(0)}ms
                    </span>
                    {h.row_count != null && <span className="tabular-nums">{h.row_count} rows</span>}
                    {h.cache_hit && (
                      <span className="flex items-center gap-0.5 text-[var(--color-success)]">
                        <Zap className="w-2.5 h-2.5" /> cached
                      </span>
                    )}
                    <span className="tabular-nums ml-auto">{new Date(h.ts).toLocaleTimeString()}</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Empty state when no history and no result */}
      {history.length === 0 && !result && !error && !executing && (
        <div className="mt-8">
          <EmptyState
            icon={EmptyQuery}
            title="ready for queries"
            description="write sql above and tap execute to run governed queries"
          />
        </div>
      )}

      {/* Mobile floating execute button — visible when results/history are showing */}
      {(result || error || history.length > 0) && (
        <button
          onClick={() => {
            window.scrollTo({ top: 0, behavior: "smooth" });
            setTimeout(() => textareaRef.current?.focus(), 400);
          }}
          className="sm:hidden fixed right-4 bottom-[calc(3.5rem+env(safe-area-inset-bottom,0px)+0.75rem)] z-40 flex items-center gap-2 px-4 py-3 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase shadow-lg active:scale-95 transition-transform"
        >
          <Play className="w-4 h-4" />
          edit query
        </button>
      )}
    </div>
  );
}
