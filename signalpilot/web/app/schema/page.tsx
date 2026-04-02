"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Database,
  Table2,
  Columns3,
  Loader2,
  ChevronRight,
  ChevronDown,
  Search,
  RefreshCw,
  Key,
  Shield,
} from "lucide-react";
import { getConnections, getConnectionSchema, detectPII } from "@/lib/api";
import type { ConnectionInfo } from "@/lib/types";
import { PullToRefreshWrapper } from "@/components/ui/pull-to-refresh";
import { EmptyDatabase, EmptyState } from "@/components/ui/empty-states";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot, StackedBar } from "@/components/ui/data-viz";
import { Tooltip } from "@/components/ui/tooltip";

interface Column {
  name: string;
  type: string;
  nullable: boolean;
  primary_key?: boolean;
}

interface TableSchema {
  schema: string;
  name: string;
  columns: Column[];
}

interface SchemaData {
  connection_name: string;
  db_type: string;
  table_count: number;
  tables: Record<string, TableSchema>;
}

const typeColorMap: Record<string, string> = {
  integer: "text-blue-400", bigint: "text-blue-400", smallint: "text-blue-400",
  int: "text-blue-400", int4: "text-blue-400", int8: "text-blue-400", serial: "text-blue-400",
  numeric: "text-cyan-400", decimal: "text-cyan-400", real: "text-cyan-400",
  "double precision": "text-cyan-400", float: "text-cyan-400", float8: "text-cyan-400",
  text: "text-green-400", varchar: "text-green-400", "character varying": "text-green-400", char: "text-green-400",
  boolean: "text-yellow-400", bool: "text-yellow-400",
  timestamp: "text-purple-400", "timestamp with time zone": "text-purple-400",
  "timestamp without time zone": "text-purple-400", timestamptz: "text-purple-400",
  date: "text-purple-400", time: "text-purple-400",
  json: "text-orange-400", jsonb: "text-orange-400",
  uuid: "text-pink-400",
};

function getTypeColor(type: string): string {
  return typeColorMap[type.toLowerCase()] || "text-[var(--color-text-dim)]";
}

/* ── Type legend SVG dots ── */
function TypeLegend() {
  const types = [
    { label: "int", color: "text-blue-400" },
    { label: "float", color: "text-cyan-400" },
    { label: "text", color: "text-green-400" },
    { label: "bool", color: "text-yellow-400" },
    { label: "time", color: "text-purple-400" },
    { label: "json", color: "text-orange-400" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {types.map(t => (
        <div key={t.label} className="flex items-center gap-1">
          <span className={`w-1.5 h-1.5 ${t.color.replace("text-", "bg-")}`} />
          <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">{t.label}</span>
        </div>
      ))}
    </div>
  );
}

export default function SchemaExplorerPage() {
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [selectedConn, setSelectedConn] = useState<string>("");
  const [schema, setSchema] = useState<SchemaData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedTables, setExpandedTables] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [piiDetections, setPiiDetections] = useState<Record<string, string> | null>(null);
  const [scanningPii, setScanningPii] = useState(false);

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

  const loadSchema = useCallback(async () => {
    if (!selectedConn) return;
    setLoading(true);
    setError(null);
    setPiiDetections(null);
    try {
      const data = await getConnectionSchema(selectedConn) as SchemaData;
      setSchema(data);
      const keys = Object.keys(data.tables).slice(0, 5);
      setExpandedTables(new Set(keys));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [selectedConn]);

  const scanPii = useCallback(async () => {
    if (!selectedConn) return;
    setScanningPii(true);
    try {
      const result = await detectPII(selectedConn);
      const flat: Record<string, string> = {};
      for (const [, cols] of Object.entries(result.detections)) {
        for (const [col, rule] of Object.entries(cols)) {
          flat[col.toLowerCase()] = rule;
        }
      }
      setPiiDetections(flat);
    } catch {} finally {
      setScanningPii(false);
    }
  }, [selectedConn]);

  useEffect(() => {
    if (selectedConn) loadSchema();
  }, [selectedConn, loadSchema]);

  function toggleTable(key: string) {
    setExpandedTables((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function expandAll() {
    if (!schema) return;
    setExpandedTables(new Set(Object.keys(schema.tables)));
  }

  function collapseAll() {
    setExpandedTables(new Set());
  }

  const filteredTables = schema
    ? Object.entries(schema.tables).filter(([key, table]) => {
        if (!search) return true;
        const lower = search.toLowerCase();
        return (
          key.toLowerCase().includes(lower) ||
          table.name.toLowerCase().includes(lower) ||
          table.columns.some((c) => c.name.toLowerCase().includes(lower))
        );
      })
    : [];

  return (
    <PullToRefreshWrapper onRefresh={loadSchema}>
    <div className="p-4 sm:p-8 animate-fade-in">
      <PageHeader
        title="schema"
        subtitle="explorer"
        description="browse tables, columns, and types"
        actions={
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={selectedConn}
            onChange={(e) => setSelectedConn(e.target.value)}
            className="px-3 py-2.5 sm:py-2 bg-[var(--color-bg-card)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] min-w-[150px] sm:min-w-[200px] tracking-wide"
          >
            {connections.length === 0 ? (
              <option value="">no connections</option>
            ) : (
              connections.map((c) => (
                <option key={c.name} value={c.name}>{c.name} ({c.db_type})</option>
              ))
            )}
          </select>
          <button
            onClick={loadSchema}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} strokeWidth={1.5} />
            refresh
          </button>
        </div>
        }
      />

      <TerminalBar
        path={`schema ${selectedConn || "—"} --introspect`}
        status={<StatusDot status={schema ? "healthy" : loading ? "unknown" : "error"} size={4} pulse={loading} />}
      >
        <div className="flex items-center gap-3 sm:gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">tables: <code className="text-[10px] text-[var(--color-text)]">{schema ? Object.keys(schema.tables).length : "—"}</code></span>
          <span className="text-[var(--color-text-dim)]">db: <code className="text-[10px] text-[var(--color-text)]">{schema?.db_type || "—"}</code></span>
        </div>
      </TerminalBar>

      {/* Search + stats + type legend */}
      {schema && (
        <div className="space-y-3 mb-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2 flex-1 min-w-0 sm:min-w-[200px]">
              <Search className="w-3.5 h-3.5 text-[var(--color-text-dim)] flex-shrink-0" strokeWidth={1.5} />
              <input
                type="text"
                placeholder="search tables and columns..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="flex-1 px-3 py-2.5 sm:py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
              />
            </div>
            <div className="flex items-center gap-3 text-[10px] text-[var(--color-text-dim)] tracking-wider">
              <span className="flex items-center gap-1">
                <Table2 className="w-3 h-3" strokeWidth={1.5} />
                {schema.table_count} tables
              </span>
              <span className="flex items-center gap-1">
                <Columns3 className="w-3 h-3" strokeWidth={1.5} />
                {Object.values(schema.tables).reduce((sum, t) => sum + t.columns.length, 0)} cols
              </span>
            </div>
            <div className="flex items-center gap-1 flex-wrap">
              <button
                onClick={scanPii}
                disabled={scanningPii}
                className="flex items-center gap-1 px-3 py-2.5 sm:py-1 text-[10px] text-[var(--color-warning)] hover:bg-[var(--color-warning)]/5 transition-colors disabled:opacity-50 tracking-wider active:bg-[var(--color-warning)]/10"
              >
                {scanningPii ? <Loader2 className="w-3 h-3 animate-spin" /> : <Shield className="w-3 h-3" strokeWidth={1.5} />}
                {piiDetections ? `pii: ${Object.keys(piiDetections).length}` : "scan pii"}
              </button>
              <button onClick={expandAll} className="px-3 py-2.5 sm:py-1 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider active:text-[var(--color-text)]">
                expand
              </button>
              <button onClick={collapseAll} className="px-3 py-2.5 sm:py-1 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider active:text-[var(--color-text)]">
                collapse
              </button>
            </div>
          </div>
          <TypeLegend />

          {/* Column type distribution bar */}
          {(() => {
            const allCols = Object.values(schema.tables).flatMap(t => t.columns);
            const typeCounts: Record<string, number> = {};
            for (const col of allCols) {
              const baseType = col.type.toLowerCase().replace(/\(.*\)/, "").trim();
              const category =
                /^(int|bigint|smallint|serial|int[248])$/.test(baseType) ? "int" :
                /^(numeric|decimal|real|double|float|float[48])/.test(baseType) ? "float" :
                /^(text|varchar|char)/.test(baseType) ? "text" :
                /^(bool)/.test(baseType) ? "bool" :
                /^(timestamp|date|time)/.test(baseType) ? "time" :
                /^(json)/.test(baseType) ? "json" :
                /^(uuid)/.test(baseType) ? "uuid" :
                "other";
              typeCounts[category] = (typeCounts[category] || 0) + 1;
            }
            const segments = [
              { value: typeCounts.int || 0, color: "#60a5fa", label: `int: ${typeCounts.int || 0}` },
              { value: typeCounts.float || 0, color: "#22d3ee", label: `float: ${typeCounts.float || 0}` },
              { value: typeCounts.text || 0, color: "#4ade80", label: `text: ${typeCounts.text || 0}` },
              { value: typeCounts.bool || 0, color: "#facc15", label: `bool: ${typeCounts.bool || 0}` },
              { value: typeCounts.time || 0, color: "#a78bfa", label: `time: ${typeCounts.time || 0}` },
              { value: typeCounts.json || 0, color: "#fb923c", label: `json: ${typeCounts.json || 0}` },
              { value: (typeCounts.uuid || 0) + (typeCounts.other || 0), color: "#94a3b8", label: `other: ${(typeCounts.uuid || 0) + (typeCounts.other || 0)}` },
            ].filter(s => s.value > 0);
            if (segments.length === 0) return null;
            return (
              <Tooltip content={segments.map(s => s.label).join(" · ")} position="bottom">
                <div className="cursor-default w-full max-w-[400px] [&>svg]:w-full">
                  <StackedBar segments={segments} width={400} height={4} />
                </div>
              </Tooltip>
            );
          })()}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mb-4 p-4 border border-[var(--color-error)]/30 bg-[var(--color-error)]/5 animate-fade-in">
          <p className="text-xs text-[var(--color-error)]">{error}</p>
        </div>
      )}

      {/* Loading */}
      {loading && !schema && (
        <div className="flex flex-col items-center justify-center py-24">
          <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)] mb-3" />
          <p className="text-xs text-[var(--color-text-dim)] tracking-wider">loading schema...</p>
        </div>
      )}

      {/* Empty */}
      {!loading && !schema && !error && (
        <EmptyState
          icon={EmptyDatabase}
          title="select a connection to explore"
          description="choose a database connection above to browse its schema"
        />
      )}

      {/* Schema tree */}
      {schema && (
        <div className="space-y-px stagger-fade-in">
          {filteredTables.length === 0 ? (
            <div className="text-center py-12 text-xs text-[var(--color-text-dim)]">
              no tables matching &ldquo;{search}&rdquo;
            </div>
          ) : (
            filteredTables.map(([key, table]) => {
              const expanded = expandedTables.has(key);
              return (
                <div key={key} className="bg-[var(--color-bg-card)] border border-[var(--color-border)] overflow-hidden card-accent-top">
                  <button
                    onClick={() => toggleTable(key)}
                    className="w-full flex items-center gap-3 px-4 py-3.5 sm:py-2.5 hover:bg-[var(--color-bg-hover)] active:bg-[var(--color-bg-hover)] transition-colors text-left group"
                  >
                    {expanded ? (
                      <ChevronDown className="w-3 h-3 text-[var(--color-text-dim)]" />
                    ) : (
                      <ChevronRight className="w-3 h-3 text-[var(--color-text-dim)]" />
                    )}
                    {/* Tree-style table icon SVG */}
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="flex-shrink-0">
                      <rect x="1" y="1" width="12" height="12" stroke="var(--color-text-muted)" strokeWidth="1" fill="none" rx="0" />
                      <line x1="1" y1="5" x2="13" y2="5" stroke="var(--color-text-dim)" strokeWidth="0.5" />
                      <line x1="5" y1="1" x2="5" y2="13" stroke="var(--color-text-dim)" strokeWidth="0.5" />
                    </svg>
                    <span className="text-xs text-[var(--color-text-muted)] group-hover:text-[var(--color-text)] transition-colors">{table.name}</span>
                    <span className="text-[10px] text-[var(--color-text-dim)] tracking-wider">{table.schema}</span>
                    <span className="ml-auto text-[10px] text-[var(--color-text-dim)] tabular-nums tracking-wider">
                      {table.columns.length} cols
                    </span>
                  </button>

                  {expanded && (
                    <div className="border-t border-[var(--color-border)]">
                      {/* Mobile column list */}
                      <div className="sm:hidden divide-y divide-[var(--color-border)]/20">
                        {table.columns.map((col, i) => (
                          <div key={col.name} className="px-3 py-2.5 flex items-start gap-3">
                            <span className="text-[9px] text-[var(--color-text-dim)] tabular-nums w-5 text-right flex-shrink-0 mt-0.5 opacity-50">{i + 1}</span>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1">
                                {col.primary_key && <Key className="w-2.5 h-2.5 text-[var(--color-warning)] flex-shrink-0" />}
                                <span className="text-[11px] text-[var(--color-text-muted)] truncate">{col.name}</span>
                              </div>
                              <div className="flex flex-wrap items-center gap-2">
                                <span className={`${getTypeColor(col.type)} text-[10px] flex items-center gap-1`}>
                                  <span className={`w-1 h-1 ${getTypeColor(col.type).replace("text-", "bg-")}`} />
                                  {col.type}
                                </span>
                                {!col.nullable && (
                                  <span className="text-[9px] text-[var(--color-warning)] tracking-wider">NOT NULL</span>
                                )}
                                {piiDetections && piiDetections[col.name.toLowerCase()] && (
                                  <span className={`text-[9px] px-1.5 py-0.5 border tracking-wider uppercase ${
                                    piiDetections[col.name.toLowerCase()] === "drop"
                                      ? "badge-error"
                                      : piiDetections[col.name.toLowerCase()] === "hash"
                                        ? "border-purple-500/30 text-purple-400"
                                        : "badge-warning"
                                  }`}>
                                    {piiDetections[col.name.toLowerCase()]}
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>

                      {/* Desktop column table */}
                      <div className="hidden sm:block overflow-x-auto">
                        <table className="w-full text-[11px] min-w-[480px]">
                          <thead>
                            <tr className="border-b border-[var(--color-border)]/50">
                              <th className="text-left px-4 py-2 text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] w-8">#</th>
                              <th className="text-left px-4 py-2 text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">column</th>
                              <th className="text-left px-4 py-2 text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">type</th>
                              <th className="text-left px-4 py-2 text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] w-24">nullable</th>
                              {piiDetections && (
                                <th className="text-left px-4 py-2 text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] w-20">pii</th>
                              )}
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-[var(--color-border)]/20">
                            {table.columns.map((col, i) => (
                              <tr key={col.name} className="table-row-hover">
                                <td className="px-4 py-1.5 text-[var(--color-text-dim)] tabular-nums">{i + 1}</td>
                                <td className="px-4 py-1.5">
                                  <span className="flex items-center gap-2">
                                    {col.primary_key && <Key className="w-2.5 h-2.5 text-[var(--color-warning)]" />}
                                    <span className="text-[var(--color-text-muted)]">{col.name}</span>
                                  </span>
                                </td>
                                <td className="px-4 py-1.5">
                                  <span className={`${getTypeColor(col.type)} flex items-center gap-1.5`}>
                                    <span className={`w-1 h-1 ${getTypeColor(col.type).replace("text-", "bg-")}`} />
                                    {col.type}
                                  </span>
                                </td>
                                <td className="px-4 py-1.5">
                                  {col.nullable ? (
                                    <span className="text-[var(--color-text-dim)]">nullable</span>
                                  ) : (
                                    <span className="text-[var(--color-warning)]">NOT NULL</span>
                                  )}
                                </td>
                                {piiDetections && (
                                  <td className="px-4 py-1.5">
                                    {piiDetections[col.name.toLowerCase()] && (
                                      <span className={`text-[9px] px-1.5 py-0.5 border tracking-wider uppercase ${
                                        piiDetections[col.name.toLowerCase()] === "drop"
                                          ? "badge-error"
                                          : piiDetections[col.name.toLowerCase()] === "hash"
                                            ? "border-purple-500/30 text-purple-400"
                                            : "badge-warning"
                                      }`}>
                                        {piiDetections[col.name.toLowerCase()]}
                                      </span>
                                    )}
                                  </td>
                                )}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
    </PullToRefreshWrapper>
  );
}
