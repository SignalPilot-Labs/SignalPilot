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
} from "lucide-react";
import { getConnections, executeQuery as apiExecuteQuery } from "@/lib/api";
import type { ConnectionInfo } from "@/lib/types";

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

export default function QueryExplorerPage() {
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [selectedConn, setSelectedConn] = useState<string>("");
  const [sql, setSql] = useState<string>("");
  const [rowLimit, setRowLimit] = useState<number>(1000);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<
    { sql: string; connection: string; ts: number; duration_ms: number; row_count?: number; cache_hit?: boolean }[]
  >([]);
  const [copied, setCopied] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Load history from localStorage on mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem(HISTORY_KEY);
      if (stored) setHistory(JSON.parse(stored));
    } catch {}
  }, []);

  useEffect(() => {
    getConnections()
      .then((conns) => {
        setConnections(conns);
        if (conns.length > 0 && !selectedConn) {
          setSelectedConn(conns[0].name);
        }
      })
      .catch(() => {});
  }, []);

  const runQuery = useCallback(async () => {
    if (!sql.trim() || !selectedConn) return;
    setExecuting(true);
    setError(null);
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
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setExecuting(false);
    }
  }, [sql, selectedConn, rowLimit, history]);

  function handleKeyDown(e: React.KeyboardEvent) {
    // Ctrl/Cmd + Enter to execute
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      runQuery();
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
  }

  return (
    <div className="p-8 flex flex-col h-screen max-h-screen">
      <div className="flex items-center justify-between mb-6 flex-shrink-0">
        <div>
          <h1 className="text-2xl font-semibold mb-1">Query Explorer</h1>
          <p className="text-sm text-[var(--color-text-muted)]">
            Run governed, read-only SQL queries against your databases
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Shield className="w-4 h-4 text-[var(--color-success)]" />
          <span className="text-xs text-[var(--color-text-muted)]">
            Read-only &middot; DDL/DML blocked &middot; LIMIT enforced
          </span>
        </div>
      </div>

      {/* Connection bar + controls */}
      <div className="flex items-center gap-3 mb-4 flex-shrink-0">
        <div className="relative">
          <select
            value={selectedConn}
            onChange={(e) => setSelectedConn(e.target.value)}
            className="appearance-none pl-3 pr-8 py-2 rounded-lg bg-[var(--color-bg-card)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)] min-w-[200px]"
          >
            {connections.length === 0 ? (
              <option value="">No connections</option>
            ) : (
              connections.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name} ({c.db_type})
                </option>
              ))
            )}
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--color-text-dim)] pointer-events-none" />
        </div>

        <div className="flex items-center gap-1.5">
          <label className="text-xs text-[var(--color-text-muted)]">Limit:</label>
          <input
            type="number"
            value={rowLimit}
            onChange={(e) =>
              setRowLimit(Math.max(1, Math.min(100000, Number(e.target.value) || 1000)))
            }
            className="w-24 px-2 py-2 rounded-lg bg-[var(--color-bg-card)] border border-[var(--color-border)] text-sm text-center focus:outline-none focus:border-[var(--color-accent)]"
          />
        </div>

        <div className="flex-1" />

        <button
          onClick={runQuery}
          disabled={executing || !sql.trim() || !selectedConn}
          className="flex items-center gap-2 px-5 py-2 rounded-lg bg-[var(--color-accent)] hover:bg-[var(--color-accent-hover)] text-white text-sm font-medium transition-colors disabled:opacity-50"
        >
          {executing ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Play className="w-4 h-4" />
          )}
          Execute
        </button>
      </div>

      {/* SQL editor */}
      <div className="relative mb-4 flex-shrink-0">
        <textarea
          ref={textareaRef}
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="SELECT * FROM users LIMIT 10;   (Ctrl+Enter to execute)"
          rows={6}
          spellCheck={false}
          className="w-full px-4 py-3 rounded-xl bg-[var(--color-bg-card)] border border-[var(--color-border)] text-sm font-mono focus:outline-none focus:border-[var(--color-accent)] resize-y placeholder:text-[var(--color-text-dim)]"
        />
        <div className="absolute bottom-3 right-3 text-[10px] text-[var(--color-text-dim)]">
          {sql.length > 0 && `${sql.length} chars`}
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="mb-4 flex items-start gap-3 p-4 rounded-xl bg-[var(--color-error)]/5 border border-[var(--color-error)]/20 flex-shrink-0">
          <XCircle className="w-4 h-4 text-[var(--color-error)] mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-medium text-[var(--color-error)] mb-1">
              Query Error
            </p>
            <p className="text-xs text-[var(--color-text-muted)]">{error}</p>
          </div>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="flex-1 flex flex-col min-h-0 bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl overflow-hidden">
          {/* Result header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)] flex-shrink-0">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5 text-xs text-[var(--color-success)]">
                <Table2 className="w-3.5 h-3.5" />
                {result.row_count.toLocaleString()} row
                {result.row_count !== 1 ? "s" : ""}
              </span>
              <span className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
                <Clock className="w-3.5 h-3.5" />
                {result.execution_ms.toFixed(0)}ms
              </span>
              {result.tables.length > 0 && (
                <span className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
                  <Database className="w-3.5 h-3.5" />
                  {result.tables.join(", ")}
                </span>
              )}
              {result.cache_hit && (
                <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-[var(--color-success)]/10 text-[var(--color-success)] font-medium">
                  <Zap className="w-3 h-3" /> Cached
                </span>
              )}
              {result.cost_estimate && (
                <span className={`flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full font-medium ${
                  result.cost_estimate.is_expensive
                    ? "bg-[var(--color-error)]/10 text-[var(--color-error)]"
                    : "bg-[var(--color-bg)] text-[var(--color-text-dim)]"
                }`}>
                  <DollarSign className="w-3 h-3" />
                  ~${result.cost_estimate.estimated_usd.toFixed(6)}
                </span>
              )}
              {result.pii_redacted && result.pii_redacted.length > 0 && (
                <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400 font-medium">
                  <Shield className="w-3 h-3" /> PII redacted ({result.pii_redacted.length})
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={copyResults}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-colors"
              >
                {copied ? (
                  <Check className="w-3.5 h-3.5 text-[var(--color-success)]" />
                ) : (
                  <Copy className="w-3.5 h-3.5" />
                )}
                {copied ? "Copied" : "Copy"}
              </button>
              <button
                onClick={exportCSV}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                CSV
              </button>
            </div>
          </div>

          {/* Result table */}
          <div className="flex-1 overflow-auto">
            {result.rows.length === 0 ? (
              <div className="flex items-center justify-center py-12 text-sm text-[var(--color-text-dim)]">
                Query returned 0 rows
              </div>
            ) : (
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-[var(--color-bg-card)]">
                  <tr className="border-b border-[var(--color-border)]">
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-[var(--color-text-dim)] uppercase tracking-wider w-10">
                      #
                    </th>
                    {Object.keys(result.rows[0]).map((col) => (
                      <th
                        key={col}
                        className="px-3 py-2 text-left text-[10px] font-medium text-[var(--color-text-muted)] uppercase tracking-wider"
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-border)]/50">
                  {result.rows.map((row, i) => (
                    <tr
                      key={i}
                      className="hover:bg-[var(--color-bg-hover)] transition-colors"
                    >
                      <td className="px-3 py-1.5 text-[var(--color-text-dim)] tabular-nums">
                        {i + 1}
                      </td>
                      {Object.values(row).map((val, j) => (
                        <td
                          key={j}
                          className="px-3 py-1.5 text-[var(--color-text)] max-w-[300px] truncate"
                          title={val == null ? "NULL" : String(val)}
                        >
                          {val == null ? (
                            <span className="text-[var(--color-text-dim)] italic">
                              NULL
                            </span>
                          ) : typeof val === "number" ? (
                            <span className="tabular-nums text-[var(--color-accent)]">
                              {val.toLocaleString()}
                            </span>
                          ) : typeof val === "boolean" ? (
                            <span
                              className={
                                val
                                  ? "text-[var(--color-success)]"
                                  : "text-[var(--color-error)]"
                              }
                            >
                              {String(val)}
                            </span>
                          ) : (
                            String(val)
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* SQL executed footer */}
          {result.sql_executed !== sql.trim() && (
            <div className="px-4 py-2 border-t border-[var(--color-border)] flex-shrink-0">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-3 h-3 text-[var(--color-warning)]" />
                <span className="text-[10px] text-[var(--color-text-muted)]">
                  Governed SQL (LIMIT injected):
                </span>
                <code className="text-[10px] text-[var(--color-text-dim)] font-mono truncate">
                  {result.sql_executed}
                </code>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Query history sidebar */}
      {history.length > 0 && !result && !error && (
        <div className="mt-4 bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
            <h3 className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wider">
              Recent Queries ({history.length})
            </h3>
            <button
              onClick={() => { setHistory([]); localStorage.removeItem(HISTORY_KEY); }}
              className="text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-error)] transition-colors"
            >
              Clear
            </button>
          </div>
          <div className="divide-y divide-[var(--color-border)]/50 max-h-72 overflow-auto">
            {history.map((h, i) => (
              <button
                key={i}
                onClick={() => {
                  setSql(h.sql);
                  setSelectedConn(h.connection);
                }}
                className="w-full text-left px-4 py-2.5 hover:bg-[var(--color-bg-hover)] transition-colors"
              >
                <code className="text-xs text-[var(--color-text)] block truncate">
                  {h.sql}
                </code>
                <div className="flex items-center gap-3 mt-1 text-[10px] text-[var(--color-text-dim)]">
                  <span>{h.connection}</span>
                  <span>{h.duration_ms.toFixed(0)}ms</span>
                  {h.row_count != null && <span>{h.row_count} rows</span>}
                  {h.cache_hit && <span className="text-[var(--color-success)]">cached</span>}
                  <span>{new Date(h.ts).toLocaleTimeString()}</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
