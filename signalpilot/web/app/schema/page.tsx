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
import { getConnectionSchema, getSchemaRefreshStatus, detectPII, getConnectionSchemaDDL } from "@/lib/api";
import { useConnection } from "@/lib/connection-context";
import { EmptyDatabase, EmptyState } from "@/components/ui/empty-states";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot, StackedBar } from "@/components/ui/data-viz";
import { Tooltip } from "@/components/ui/tooltip";

interface Column {
  name: string;
  type: string;
  nullable: boolean;
  primary_key?: boolean;
  comment?: string;
  stats?: { distinct_count?: number; distinct_fraction?: number; data_bytes?: number; compressed_bytes?: number };
  encoding?: string;
  dist_key?: boolean;
  sort_key_position?: number;
  low_cardinality?: boolean;
}

interface ForeignKey {
  column: string;
  references_table: string;
  references_column: string;
  references_schema?: string;
}

interface TableSchema {
  schema: string;
  name: string;
  columns: Column[];
  foreign_keys?: ForeignKey[];
  row_count?: number;
  description?: string;
  engine?: string;
  sorting_key?: string;
  diststyle?: string;
  sortkey?: string;
  clustering_key?: string;
  size_mb?: number;
  total_bytes?: number;
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
    <div className="flex items-center gap-3">
      {types.map(t => (
        <div key={t.label} className="flex items-center gap-1">
          <span className={`w-1.5 h-1.5 ${t.color.replace("text-", "bg-")}`} />
          <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider">{t.label}</span>
        </div>
      ))}
    </div>
  );
}

export default function SchemaExplorerPage() {
  const { connections, selectedConn, setSelectedConn } = useConnection();
  const [schema, setSchema] = useState<SchemaData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedTables, setExpandedTables] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [piiDetections, setPiiDetections] = useState<Record<string, string> | null>(null);
  const [scanningPii, setScanningPii] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<number | null>(null);
  const [refreshInterval, setRefreshInterval] = useState<number | null>(null);
  const [viewMode, setViewMode] = useState<"table" | "ddl">("table");
  const [ddlContent, setDdlContent] = useState<string>("");
  const [ddlLoading, setDdlLoading] = useState(false);
  const [ddlTokens, setDdlTokens] = useState(0);

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
      // Fetch refresh status
      getSchemaRefreshStatus(selectedConn).then((status) => {
        setLastRefresh(status.last_schema_refresh);
        setRefreshInterval(status.schema_refresh_interval);
      }).catch(() => {});
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

  const loadDDL = useCallback(async () => {
    if (!selectedConn) return;
    setDdlLoading(true);
    try {
      const data = await getConnectionSchemaDDL(selectedConn);
      setDdlContent(data.ddl);
      setDdlTokens(data.token_estimate);
    } catch {
      setDdlContent("-- Failed to load DDL");
    } finally {
      setDdlLoading(false);
    }
  }, [selectedConn]);

  useEffect(() => {
    if (selectedConn) {
      loadSchema();
      if (viewMode === "ddl") loadDDL();
    }
  }, [selectedConn, loadSchema, viewMode, loadDDL]);

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
    <div className="p-8 animate-fade-in">
      <PageHeader
        title="schema"
        subtitle="explorer"
        description="browse tables, columns, and types"
        actions={
        <div className="flex items-center gap-3">
          <select
            value={selectedConn}
            onChange={(e) => setSelectedConn(e.target.value)}
            className="px-3 py-2 bg-[var(--color-bg-card)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] min-w-[200px] tracking-wide"
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
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">tables: <code className="text-[12px] text-[var(--color-text)]">{schema ? Object.keys(schema.tables).length : "—"}</code></span>
          <span className="text-[var(--color-text-dim)]">columns: <code className="text-[12px] text-[var(--color-text)]">{schema ? Object.values(schema.tables).reduce((sum, t) => sum + t.columns.length, 0) : "—"}</code></span>
          <span className="text-[var(--color-text-dim)]">db: <code className="text-[12px] text-[var(--color-text)]">{schema?.db_type || "—"}</code></span>
          {lastRefresh && (
            <span className="text-[var(--color-text-dim)]">
              refreshed: <code className="text-[12px] text-[var(--color-text)]">{new Date(lastRefresh * 1000).toLocaleTimeString()}</code>
              {refreshInterval && <span className="ml-1 opacity-60">(every {refreshInterval >= 3600 ? `${Math.round(refreshInterval / 3600)}h` : `${Math.round(refreshInterval / 60)}m`})</span>}
            </span>
          )}
        </div>
      </TerminalBar>

      {/* Search + stats + type legend */}
      {schema && (
        <div className="space-y-3 mb-4">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 flex-1">
              <Search className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
              <input
                type="text"
                placeholder="search tables and columns..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="flex-1 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
              />
            </div>
            <div className="flex items-center gap-3 text-[12px] text-[var(--color-text-dim)] tracking-wider">
              <span className="flex items-center gap-1">
                <Table2 className="w-3 h-3" strokeWidth={1.5} />
                {schema.table_count} tables
              </span>
              <span className="flex items-center gap-1">
                <Columns3 className="w-3 h-3" strokeWidth={1.5} />
                {Object.values(schema.tables).reduce((sum, t) => sum + t.columns.length, 0)} cols
              </span>
            </div>
            <div className="flex items-center gap-1">
              {/* View mode toggle */}
              <div className="flex items-center border border-[var(--color-border)] mr-2">
                <button
                  onClick={() => setViewMode("table")}
                  className={`px-2 py-1 text-[12px] tracking-wider transition-colors ${viewMode === "table" ? "bg-[var(--color-text)]/10 text-[var(--color-text)]" : "text-[var(--color-text-dim)] hover:text-[var(--color-text)]"}`}
                >
                  table
                </button>
                <button
                  onClick={() => { setViewMode("ddl"); if (!ddlContent) loadDDL(); }}
                  className={`px-2 py-1 text-[12px] tracking-wider transition-colors ${viewMode === "ddl" ? "bg-[var(--color-text)]/10 text-[var(--color-text)]" : "text-[var(--color-text-dim)] hover:text-[var(--color-text)]"}`}
                >
                  DDL
                </button>
              </div>
              <button
                onClick={scanPii}
                disabled={scanningPii}
                className="flex items-center gap-1 px-2 py-1 text-[12px] text-[var(--color-warning)] hover:bg-[var(--color-warning)]/5 transition-colors disabled:opacity-50 tracking-wider"
              >
                {scanningPii ? <Loader2 className="w-3 h-3 animate-spin" /> : <Shield className="w-3 h-3" strokeWidth={1.5} />}
                {piiDetections ? `pii: ${Object.keys(piiDetections).length}` : "scan pii"}
              </button>
              {viewMode === "table" && (
                <>
                  <button onClick={expandAll} className="px-2 py-1 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider">
                    expand
                  </button>
                  <button onClick={collapseAll} className="px-2 py-1 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider">
                    collapse
                  </button>
                </>
              )}
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
                <div className="cursor-default">
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

      {/* DDL view */}
      {schema && viewMode === "ddl" && (
        <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] animate-fade-in">
          <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-border)]">
            <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider uppercase">create table ddl</span>
            <div className="flex items-center gap-3 text-[11px] text-[var(--color-text-dim)] tracking-wider">
              {ddlTokens > 0 && <span>~{ddlTokens.toLocaleString()} tokens</span>}
              <button
                onClick={() => navigator.clipboard.writeText(ddlContent)}
                className="hover:text-[var(--color-text)] transition-colors"
              >
                copy
              </button>
            </div>
          </div>
          {ddlLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-dim)]" />
            </div>
          ) : (
            <pre className="px-4 py-3 text-[13px] text-[var(--color-text-muted)] overflow-x-auto font-mono leading-relaxed max-h-[600px] overflow-y-auto whitespace-pre">
              {ddlContent || "-- No DDL available"}
            </pre>
          )}
        </div>
      )}

      {/* Schema tree */}
      {schema && viewMode === "table" && (
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
                    className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-[var(--color-bg-hover)] transition-colors text-left group"
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
                    <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider">{table.schema}</span>
                    {(table.foreign_keys?.length ?? 0) > 0 && (
                      <span className="text-[11px] px-1 py-0.5 border border-blue-500/20 text-blue-400 tracking-wider tabular-nums">
                        {table.foreign_keys!.length} FK{table.foreign_keys!.length > 1 ? "s" : ""}
                      </span>
                    )}
                    {table.description && (
                      <span className="text-[11px] text-[var(--color-text-dim)] italic tracking-wider truncate max-w-[200px]">
                        {table.description}
                      </span>
                    )}
                    {table.engine && (
                      <span className="text-[11px] px-1 py-0.5 border border-[var(--color-border)] text-[var(--color-text-dim)] tracking-wider">
                        {table.engine}
                      </span>
                    )}
                    {table.diststyle && (
                      <span className="text-[11px] px-1 py-0.5 border border-orange-500/20 text-orange-400 tracking-wider">
                        DIST:{table.diststyle}
                      </span>
                    )}
                    {table.sortkey && (
                      <span className="text-[11px] px-1 py-0.5 border border-amber-500/20 text-amber-400 tracking-wider">
                        SORT:{table.sortkey}
                      </span>
                    )}
                    {table.clustering_key && (
                      <span className="text-[11px] px-1 py-0.5 border border-cyan-500/20 text-cyan-400 tracking-wider">
                        CLUSTER:{table.clustering_key}
                      </span>
                    )}
                    {table.sorting_key && (
                      <span className="text-[11px] px-1 py-0.5 border border-violet-500/20 text-violet-400 tracking-wider">
                        ORDER:{table.sorting_key}
                      </span>
                    )}
                    <span className="ml-auto flex items-center gap-3 text-[12px] text-[var(--color-text-dim)] tabular-nums tracking-wider">
                      {table.row_count != null && table.row_count > 0 && (
                        <span className="opacity-60">
                          {table.row_count >= 1_000_000
                            ? `${(table.row_count / 1_000_000).toFixed(1)}M`
                            : table.row_count >= 1_000
                              ? `${(table.row_count / 1_000).toFixed(0)}K`
                              : table.row_count} rows
                        </span>
                      )}
                      {table.size_mb != null && table.size_mb > 0 && (
                        <span className="opacity-60">
                          {table.size_mb >= 1024
                            ? `${(table.size_mb / 1024).toFixed(1)}GB`
                            : `${table.size_mb.toFixed(0)}MB`}
                        </span>
                      )}
                      {!table.size_mb && table.total_bytes != null && table.total_bytes > 0 && (
                        <span className="opacity-60">
                          {table.total_bytes >= 1_073_741_824
                            ? `${(table.total_bytes / 1_073_741_824).toFixed(1)}GB`
                            : table.total_bytes >= 1_048_576
                              ? `${(table.total_bytes / 1_048_576).toFixed(0)}MB`
                              : `${(table.total_bytes / 1024).toFixed(0)}KB`}
                        </span>
                      )}
                      {table.columns.length} cols
                    </span>
                  </button>

                  {expanded && (
                    <div className="border-t border-[var(--color-border)]">
                      <table className="w-full text-[13px]">
                        <thead>
                          <tr className="border-b border-[var(--color-border)]/50">
                            <th className="text-left px-4 py-2 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] w-8">#</th>
                            <th className="text-left px-4 py-2 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">column</th>
                            <th className="text-left px-4 py-2 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">type</th>
                            <th className="text-left px-4 py-2 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] w-24">nullable</th>
                            <th className="text-left px-4 py-2 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">references</th>
                            {table.columns.some(c => c.stats) && (
                              <th className="text-left px-4 py-2 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] w-24">cardinality</th>
                            )}
                            {table.columns.some(c => c.comment) && (
                              <th className="text-left px-4 py-2 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">comment</th>
                            )}
                            {piiDetections && (
                              <th className="text-left px-4 py-2 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] w-20">pii</th>
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
                                  {col.dist_key && (
                                    <span className="text-[10px] px-1 py-0.5 border border-orange-500/30 text-orange-400 tracking-wider leading-none">DK</span>
                                  )}
                                  {col.sort_key_position != null && col.sort_key_position > 0 && (
                                    <span className="text-[10px] px-1 py-0.5 border border-amber-500/30 text-amber-400 tracking-wider leading-none">SK{col.sort_key_position}</span>
                                  )}
                                  {col.low_cardinality && (
                                    <span className="text-[10px] px-1 py-0.5 border border-teal-500/30 text-teal-400 tracking-wider leading-none">LC</span>
                                  )}
                                </span>
                              </td>
                              <td className="px-4 py-1.5">
                                <span className={`${getTypeColor(col.type)} flex items-center gap-1.5`}>
                                  <span className={`w-1 h-1 ${getTypeColor(col.type).replace("text-", "bg-")}`} />
                                  {col.type}
                                  {col.encoding && col.encoding !== "none" && (
                                    <span className="text-[10px] text-[var(--color-text-dim)] opacity-60">{col.encoding}</span>
                                  )}
                                </span>
                              </td>
                              <td className="px-4 py-1.5">
                                {col.nullable ? (
                                  <span className="text-[var(--color-text-dim)]">nullable</span>
                                ) : (
                                  <span className="text-[var(--color-warning)]">NOT NULL</span>
                                )}
                              </td>
                              <td className="px-4 py-1.5">
                                {(() => {
                                  const fk = table.foreign_keys?.find(f => f.column === col.name);
                                  if (fk) {
                                    return (
                                      <span className="text-[11px] text-blue-400 tracking-wider">
                                        → {fk.references_table}.{fk.references_column}
                                      </span>
                                    );
                                  }
                                  return null;
                                })()}
                              </td>
                              {table.columns.some(c => c.stats) && (
                                <td className="px-4 py-1.5">
                                  {col.stats && (
                                    <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider tabular-nums">
                                      {col.stats.distinct_count != null
                                        ? col.stats.distinct_count >= 1000
                                          ? `${(col.stats.distinct_count / 1000).toFixed(0)}K`
                                          : col.stats.distinct_count
                                        : col.stats.distinct_fraction != null
                                          ? `${(col.stats.distinct_fraction * 100).toFixed(0)}%`
                                          : ""}
                                    </span>
                                  )}
                                </td>
                              )}
                              {table.columns.some(c => c.comment) && (
                                <td className="px-4 py-1.5">
                                  {col.comment && (
                                    <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider italic">
                                      {col.comment.length > 60 ? col.comment.slice(0, 60) + "..." : col.comment}
                                    </span>
                                  )}
                                </td>
                              )}
                              {piiDetections && (
                                <td className="px-4 py-1.5">
                                  {piiDetections[col.name.toLowerCase()] && (
                                    <span className={`text-[11px] px-1.5 py-0.5 border tracking-wider uppercase ${
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
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
