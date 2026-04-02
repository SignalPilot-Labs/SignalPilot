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

export default function QueryExplorerPage() {
  const { toast } = useToast();
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
  const lineNumbersRef = useRef<HTMLDivElement>(null);

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
              <span className="text-[10px] text-[var(--color-success)] tracking-wider">
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
          <span className="text-[var(--color-text-dim)]">history: <code className="text-[10px] text-[var(--color-text)]">{history.length}</code></span>
          {result && <span className="text-[var(--color-success)]">rows: <code className="text-[10px]">{result.row_count}</code></span>}
        </div>
      </TerminalBar>

      {/* Connection bar + controls */}
      <div className="flex flex-wrap items-center gap-3 mb-4 flex-shrink-0">
        <div className="relative flex-1 min-w-[120px] sm:min-w-[160px] sm:flex-none">
          <select
            value={selectedConn}
            onChange={(e) => setSelectedConn(e.target.value)}
            className="appearance-none w-full sm:w-auto pl-3 pr-8 py-2.5 sm:py-2 bg-[var(--color-bg-card)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] sm:min-w-[200px] tracking-wide"
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
          <label className="text-[10px] text-[var(--color-text-dim)] tracking-wider">limit:</label>
          <input
            type="number"
            value={rowLimit}
            onChange={(e) =>
              setRowLimit(Math.max(1, Math.min(100000, Number(e.target.value) || 1000)))
            }
            className="w-16 px-1 py-1 bg-transparent text-base sm:text-xs text-center focus:outline-none tabular-nums"
          />
        </div>

        <div className="hidden sm:block flex-1" />

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
          <kbd className="ml-1 px-1.5 py-0.5 bg-[var(--color-bg)]/20 text-[8px] opacity-60 border border-[var(--color-bg)]/30 hidden sm:inline">
            ctrl+⏎
          </kbd>
        </button>
      </div>

      {/* SQL editor with line numbers */}
      <div className="relative mb-4 flex-shrink-0 border border-[var(--color-border)] bg-[var(--color-bg-card)] flex overflow-hidden card-radial-glow">
        {/* Line numbers gutter */}
        <div
          ref={lineNumbersRef}
          className="flex-shrink-0 py-3 pr-0 pl-2 sm:pl-3 select-none overflow-hidden border-r border-[var(--color-border)] bg-[var(--color-bg)] w-8 sm:w-12"
        >
          {Array.from({ length: lineCount }, (_, i) => (
            <div key={i} className="text-[10px] text-[var(--color-text-dim)] text-right pr-2 leading-[1.65rem] tabular-nums opacity-50">
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
        <div className="absolute bottom-0 right-0 flex items-center gap-3 px-3 py-1.5 text-[9px] text-[var(--color-text-dim)] bg-[var(--color-bg-card)]">
          {sql.length > 0 && (
            <span className="tabular-nums">{sql.length} chars</span>
          )}
          <span className="tracking-wider opacity-60 hidden sm:inline">ctrl+enter</span>
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="mb-4 flex items-start gap-3 p-4 border border-[var(--color-error)]/30 bg-[var(--color-error)]/5 flex-shrink-0 animate-fade-in">
          <XCircle className="w-3.5 h-3.5 text-[var(--color-error)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
          <div>
            <p className="text-xs text-[var(--color-error)] mb-1 tracking-wider">query error</p>
            <p className="text-[10px] text-[var(--color-text-muted)]">{error}</p>
          </div>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="flex-1 flex flex-col min-h-0 border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden animate-fade-in">
          {/* Result header */}
          <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 border-b border-[var(--color-border)] flex-shrink-0">
            <div className="flex flex-wrap items-center gap-3 sm:gap-4">
              <span className="flex items-center gap-1.5 text-[10px] text-[var(--color-success)] tracking-wider">
                <Table2 className="w-3 h-3" strokeWidth={1.5} />
                {result.row_count.toLocaleString()} row{result.row_count !== 1 ? "s" : ""}
              </span>
              <span className="flex items-center gap-1.5 text-[10px] text-[var(--color-text-dim)] tracking-wider">
                <Clock className="w-3 h-3" strokeWidth={1.5} />
                {result.execution_ms.toFixed(0)}ms
              </span>
              {result.tables.length > 0 && (
                <span className="flex items-center gap-1.5 text-[10px] text-[var(--color-text-dim)] tracking-wider">
                  <Database className="w-3 h-3" strokeWidth={1.5} />
                  {result.tables.join(", ")}
                </span>
              )}
              {result.cache_hit && (
                <span className="flex items-center gap-1 text-[9px] px-1.5 py-0.5 border badge-success tracking-wider uppercase">
                  <Zap className="w-2.5 h-2.5" /> cached
                </span>
              )}
              {result.cost_estimate && (
                <span className={`flex items-center gap-1 text-[9px] px-1.5 py-0.5 border tracking-wider ${
                  result.cost_estimate.is_expensive ? "badge-error" : "border-[var(--color-border)] text-[var(--color-text-dim)]"
                }`}>
                  <DollarSign className="w-2.5 h-2.5" />
                  ~${result.cost_estimate.estimated_usd.toFixed(6)}
                </span>
              )}
              {result.pii_redacted && result.pii_redacted.length > 0 && (
                <span className="flex items-center gap-1 text-[9px] px-1.5 py-0.5 border badge-warning tracking-wider uppercase">
                  <Shield className="w-2.5 h-2.5" /> pii redacted ({result.pii_redacted.length})
                </span>
              )}
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={copyResults}
                className="flex items-center gap-1.5 px-2.5 py-2 sm:py-1 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider active:text-[var(--color-text)]"
              >
                {copied ? <Check className="w-3 h-3 text-[var(--color-success)]" /> : <Copy className="w-3 h-3" />}
                {copied ? "copied" : "copy"}
              </button>
              <button
                onClick={exportCSV}
                className="flex items-center gap-1.5 px-2.5 py-2 sm:py-1 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider active:text-[var(--color-text)]"
              >
                <Download className="w-3 h-3" /> csv
              </button>
              <button
                onClick={exportJSON}
                className="flex items-center gap-1.5 px-2.5 py-2 sm:py-1 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider active:text-[var(--color-text)]"
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
                        <span className="text-[9px] text-[var(--color-text-dim)] tabular-nums tracking-wider">row {i + 1}</span>
                        <button
                          onClick={() => {
                            const text = Object.entries(row).map(([k, v]) => `${k}: ${v ?? "null"}`).join("\n");
                            navigator.clipboard.writeText(text).then(() => {
                              toast(`row ${i + 1} copied`, "info");
                            }).catch(() => {});
                          }}
                          className="text-[9px] text-[var(--color-text-dim)] tracking-wider flex items-center gap-1 p-1.5 -m-1.5 active:text-[var(--color-text)]"
                        >
                          <Copy className="w-3 h-3" /> copy
                        </button>
                      </div>
                      <div className="space-y-1.5">
                        {Object.entries(row).map(([col, val], j) => {
                          const colType = inferColumnType(result.rows, col);
                          return (
                            <div key={j} className="flex items-start gap-2">
                              <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider min-w-[80px] max-w-[100px] truncate flex-shrink-0 pt-0.5 flex items-center gap-1">
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
                                  <span className="text-orange-400/80 font-mono text-[10px]">{JSON.stringify(val).slice(0, 80)}</span>
                                ) : /^\d{4}-\d{2}-\d{2}/.test(String(val)) ? (
                                  <span className="text-purple-400/80 tabular-nums">{String(val)}</span>
                                ) : /^[0-9a-f]{8}-[0-9a-f]{4}/.test(String(val)) ? (
                                  <span className="text-pink-400/70 font-mono text-[10px]">{String(val)}</span>
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
                <table className="hidden sm:table w-full text-[11px] table-fixed-header">
                  <thead className="sticky top-0 bg-[var(--color-bg-card)]">
                    <tr className="border-b border-[var(--color-border)]">
                      <th className="px-3 py-2 text-left text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] w-10">
                        #
                      </th>
                      {Object.keys(result.rows[0]).map((col) => {
                        const colType = inferColumnType(result.rows, col);
                        return (
                          <th
                            key={col}
                            className="px-3 py-2 text-left text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]"
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
                        <td className="px-3 py-1.5 text-[var(--color-text-dim)] tabular-nums text-[9px]">{i + 1}</td>
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
                              <span className="text-orange-400/80 font-mono text-[10px]">{JSON.stringify(val).slice(0, 60)}</span>
                            ) : /^\d{4}-\d{2}-\d{2}/.test(String(val)) ? (
                              <span className="text-purple-400/80 tabular-nums">{String(val)}</span>
                            ) : /^[0-9a-f]{8}-[0-9a-f]{4}/.test(String(val)) ? (
                              <span className="text-pink-400/70 font-mono text-[10px]">{String(val)}</span>
                            ) : (
                              String(val)
                            )}
                            {/* Click-to-copy hint */}
                            <span className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover/cell:opacity-100 transition-opacity text-[8px] text-[var(--color-text-dim)]">
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
                <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">
                  governed sql (limit injected):
                </span>
                <span className="text-[10px] truncate">
                  <SqlHighlight sql={result.sql_executed} className="text-[10px]" />
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
              <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                history ({history.length})
              </span>
            </div>
            <div className="flex items-center gap-3">
              {history.length >= 3 && (
                <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider tabular-nums">
                  avg: {Math.round(history.reduce((s, h) => s + h.duration_ms, 0) / history.length)}ms
                </span>
              )}
              <button
                onClick={() => { setHistory([]); localStorage.removeItem(HISTORY_KEY); }}
                className="text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-error)] transition-colors tracking-wider"
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
                <span className="text-[9px] text-[var(--color-text-dim)] tabular-nums w-5 text-right flex-shrink-0 mt-0.5 opacity-40 select-none">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[11px] block truncate overflow-hidden">
                    <SqlHighlight sql={h.sql.slice(0, 100)} className="text-[11px]" />
                  </div>
                  <div className="flex items-center gap-3 mt-1 text-[9px] text-[var(--color-text-dim)] tracking-wider">
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
            description="write sql above and press ctrl+enter to execute governed queries"
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
