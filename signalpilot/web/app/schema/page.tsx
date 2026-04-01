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
  Hash,
  Type,
  ToggleLeft,
  Shield,
  AlertTriangle,
  Ban,
  Download,
} from "lucide-react";
import { getConnections, getConnectionSchema, detectPII } from "@/lib/api";
import type { ConnectionInfo } from "@/lib/types";


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
  integer: "text-blue-400",
  bigint: "text-blue-400",
  smallint: "text-blue-400",
  int: "text-blue-400",
  int4: "text-blue-400",
  int8: "text-blue-400",
  serial: "text-blue-400",
  numeric: "text-cyan-400",
  decimal: "text-cyan-400",
  real: "text-cyan-400",
  "double precision": "text-cyan-400",
  float: "text-cyan-400",
  float8: "text-cyan-400",
  text: "text-green-400",
  varchar: "text-green-400",
  "character varying": "text-green-400",
  char: "text-green-400",
  boolean: "text-yellow-400",
  bool: "text-yellow-400",
  timestamp: "text-purple-400",
  "timestamp with time zone": "text-purple-400",
  "timestamp without time zone": "text-purple-400",
  timestamptz: "text-purple-400",
  date: "text-purple-400",
  time: "text-purple-400",
  json: "text-orange-400",
  jsonb: "text-orange-400",
  uuid: "text-pink-400",
};

function getTypeColor(type: string): string {
  const lower = type.toLowerCase();
  return typeColorMap[lower] || "text-[var(--color-text-muted)]";
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
      // Auto-expand first 5 tables
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
      // Flatten detections: { table: { col: rule } } -> { col: rule }
      const flat: Record<string, string> = {};
      for (const [, cols] of Object.entries(result.detections)) {
        for (const [col, rule] of Object.entries(cols)) {
          flat[col.toLowerCase()] = rule;
        }
      }
      setPiiDetections(flat);
    } catch {
      // PII scan is optional, don't block UX
    } finally {
      setScanningPii(false);
    }
  }, [selectedConn]);

  useEffect(() => {
    if (selectedConn) loadSchema();
  }, [selectedConn, loadSchema]);

  function toggleTable(key: string) {
    setExpandedTables((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
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
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold mb-1">Schema Explorer</h1>
          <p className="text-sm text-[var(--color-text-muted)]">
            Browse database tables, columns, and types
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={selectedConn}
            onChange={(e) => setSelectedConn(e.target.value)}
            className="px-3 py-2 rounded-lg bg-[var(--color-bg-card)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)] min-w-[200px]"
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
          <button
            onClick={loadSchema}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-colors"
          >
            <RefreshCw
              className={`w-4 h-4 ${loading ? "animate-spin" : ""}`}
            />
            Refresh
          </button>
        </div>
      </div>

      {/* Search + stats bar */}
      {schema && (
        <div className="flex items-center gap-3 mb-4">
          <div className="flex items-center gap-2 flex-1">
            <Search className="w-4 h-4 text-[var(--color-text-dim)]" />
            <input
              type="text"
              placeholder="Search tables and columns..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="flex-1 px-3 py-2 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)]"
            />
          </div>
          <div className="flex items-center gap-3 text-xs text-[var(--color-text-muted)]">
            <span className="flex items-center gap-1">
              <Table2 className="w-3.5 h-3.5" />
              {schema.table_count} tables
            </span>
            <span className="flex items-center gap-1">
              <Columns3 className="w-3.5 h-3.5" />
              {Object.values(schema.tables).reduce(
                (sum, t) => sum + t.columns.length,
                0
              )}{" "}
              columns
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={scanPii}
              disabled={scanningPii}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs text-purple-400 hover:bg-purple-500/10 transition-colors disabled:opacity-50"
            >
              {scanningPii ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Shield className="w-3 h-3" />
              )}
              {piiDetections ? `PII: ${Object.keys(piiDetections).length}` : "Scan PII"}
            </button>
            <button
              onClick={expandAll}
              className="px-2 py-1 rounded text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-colors"
            >
              Expand all
            </button>
            <button
              onClick={collapseAll}
              className="px-2 py-1 rounded text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-colors"
            >
              Collapse all
            </button>
          </div>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="mb-4 p-4 rounded-xl bg-[var(--color-error)]/5 border border-[var(--color-error)]/20">
          <p className="text-sm text-[var(--color-error)]">{error}</p>
        </div>
      )}

      {/* Loading state */}
      {loading && !schema && (
        <div className="flex flex-col items-center justify-center py-24">
          <Loader2 className="w-8 h-8 animate-spin text-[var(--color-accent)] mb-4" />
          <p className="text-sm text-[var(--color-text-muted)]">
            Loading schema...
          </p>
        </div>
      )}

      {/* Empty state */}
      {!loading && !schema && !error && (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <Database className="w-12 h-12 text-[var(--color-text-dim)] mb-4" />
          <p className="text-sm text-[var(--color-text-muted)] mb-2">
            Select a connection to explore its schema
          </p>
        </div>
      )}

      {/* Schema tree */}
      {schema && (
        <div className="space-y-1">
          {filteredTables.length === 0 ? (
            <div className="text-center py-12 text-sm text-[var(--color-text-dim)]">
              No tables matching &ldquo;{search}&rdquo;
            </div>
          ) : (
            filteredTables.map(([key, table]) => {
              const expanded = expandedTables.has(key);
              return (
                <div
                  key={key}
                  className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl overflow-hidden"
                >
                  {/* Table header */}
                  <button
                    onClick={() => toggleTable(key)}
                    className="w-full flex items-center gap-3 px-4 py-3 hover:bg-[var(--color-bg-hover)] transition-colors text-left"
                  >
                    {expanded ? (
                      <ChevronDown className="w-4 h-4 text-[var(--color-text-dim)]" />
                    ) : (
                      <ChevronRight className="w-4 h-4 text-[var(--color-text-dim)]" />
                    )}
                    <Table2 className="w-4 h-4 text-[var(--color-accent)]" />
                    <span className="text-sm font-medium">{table.name}</span>
                    <span className="text-xs text-[var(--color-text-dim)]">
                      {table.schema}
                    </span>
                    <span className="ml-auto text-xs text-[var(--color-text-dim)]">
                      {table.columns.length} columns
                    </span>
                  </button>

                  {/* Columns list */}
                  {expanded && (
                    <div className="border-t border-[var(--color-border)]">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-[var(--color-border)]/50">
                            <th className="text-left px-4 py-2 text-[10px] font-medium text-[var(--color-text-dim)] uppercase tracking-wider w-8">
                              #
                            </th>
                            <th className="text-left px-4 py-2 text-[10px] font-medium text-[var(--color-text-dim)] uppercase tracking-wider">
                              Column
                            </th>
                            <th className="text-left px-4 py-2 text-[10px] font-medium text-[var(--color-text-dim)] uppercase tracking-wider">
                              Type
                            </th>
                            <th className="text-left px-4 py-2 text-[10px] font-medium text-[var(--color-text-dim)] uppercase tracking-wider w-24">
                              Nullable
                            </th>
                            {piiDetections && (
                              <th className="text-left px-4 py-2 text-[10px] font-medium text-[var(--color-text-dim)] uppercase tracking-wider w-20">
                                PII
                              </th>
                            )}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[var(--color-border)]/30">
                          {table.columns.map((col, i) => (
                            <tr
                              key={col.name}
                              className="hover:bg-[var(--color-bg-hover)] transition-colors"
                            >
                              <td className="px-4 py-1.5 text-[var(--color-text-dim)] tabular-nums">
                                {i + 1}
                              </td>
                              <td className="px-4 py-1.5">
                                <span className="flex items-center gap-2">
                                  {col.primary_key && (
                                    <Key className="w-3 h-3 text-yellow-500" />
                                  )}
                                  <span className="font-mono text-[var(--color-text)]">
                                    {col.name}
                                  </span>
                                </span>
                              </td>
                              <td className="px-4 py-1.5">
                                <span
                                  className={`font-mono ${getTypeColor(col.type)}`}
                                >
                                  {col.type}
                                </span>
                              </td>
                              <td className="px-4 py-1.5">
                                {col.nullable ? (
                                  <span className="text-[var(--color-text-dim)]">
                                    nullable
                                  </span>
                                ) : (
                                  <span className="text-[var(--color-warning)]">
                                    NOT NULL
                                  </span>
                                )}
                              </td>
                              {piiDetections && (
                                <td className="px-4 py-1.5">
                                  {piiDetections[col.name.toLowerCase()] && (
                                    <span
                                      className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                                        piiDetections[col.name.toLowerCase()] === "drop"
                                          ? "bg-[var(--color-error)]/10 text-[var(--color-error)]"
                                          : piiDetections[col.name.toLowerCase()] === "hash"
                                            ? "bg-purple-500/10 text-purple-400"
                                            : "bg-[var(--color-warning)]/10 text-[var(--color-warning)]"
                                      }`}
                                    >
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
