"use client";

import { useEffect, useState, useCallback } from "react";
import {
  ScrollText,
  Filter,
  RefreshCw,
  ShieldAlert,
  Terminal,
  Database as DbIcon,
  Loader2,
  Download,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { getAudit, getAuditExportUrl } from "@/lib/api";
import type { AuditEntry } from "@/lib/types";
import { EmptyList, EmptyState } from "@/components/ui/empty-states";

const typeIcons: Record<string, React.ElementType> = {
  query: DbIcon,
  execute: Terminal,
  connect: DbIcon,
  block: ShieldAlert,
};

const typeColors: Record<string, string> = {
  query: "text-[var(--color-success)]",
  execute: "text-blue-400",
  block: "text-[var(--color-error)]",
  connect: "text-[var(--color-text-dim)]",
};

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("");
  const [typeFilter, setTypeFilter] = useState<string>("");
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { limit: 200 };
      if (typeFilter) params.event_type = typeFilter;
      const res = await getAudit(params);
      setEntries(res.entries);
    } catch {} finally { setLoading(false); }
  }, [typeFilter]);

  useEffect(() => { refresh(); }, [refresh]);

  function exportCSV() {
    const headers = ["timestamp", "event_type", "connection_name", "sql", "tables", "rows_returned", "duration_ms", "blocked", "block_reason"];
    const rows = filtered.map((e) =>
      headers.map((h) => {
        const val = e[h as keyof AuditEntry];
        if (h === "timestamp") return new Date((val as number) * 1000).toISOString();
        if (h === "tables") return (val as string[])?.join(";") || "";
        if (val === null || val === undefined) return "";
        return String(val).replace(/"/g, '""');
      })
    );
    const csv = [headers.join(","), ...rows.map((r) => r.map((v) => `"${v}"`).join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `signalpilot-audit-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const filtered = entries.filter((e) => {
    if (!filter) return true;
    const lower = filter.toLowerCase();
    return (
      e.sql?.toLowerCase().includes(lower) ||
      e.connection_name?.toLowerCase().includes(lower) ||
      e.event_type.includes(lower) ||
      e.block_reason?.toLowerCase().includes(lower)
    );
  });

  const statsData = {
    total: filtered.length,
    queries: filtered.filter(e => e.event_type === "query").length,
    executions: filtered.filter(e => e.event_type === "execute").length,
    blocked: filtered.filter(e => e.blocked).length,
  };

  return (
    <div className="p-8 animate-fade-in">
      <div className="flex items-center justify-between mb-8">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-lg font-light tracking-wide">audit</h1>
            <span className="text-[9px] text-[var(--color-text-dim)] tracking-[0.15em] uppercase">/ log</span>
          </div>
          <p className="text-xs text-[var(--color-text-dim)] tracking-wider">
            full-chain audit trail of all governed operations
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={exportCSV} disabled={filtered.length === 0}
            className="flex items-center gap-2 px-3 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] transition-all disabled:opacity-30 tracking-wider">
            <Download className="w-3.5 h-3.5" strokeWidth={1.5} /> csv
          </button>
          <a href={getAuditExportUrl("json", typeFilter || undefined)} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-2 px-3 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] transition-all tracking-wider">
            <Download className="w-3.5 h-3.5" strokeWidth={1.5} /> compliance
          </a>
          <button onClick={refresh}
            className="flex items-center gap-2 px-3 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} strokeWidth={1.5} /> refresh
          </button>
        </div>
      </div>

      {/* Stats bar */}
      {entries.length > 0 && (
        <div className="flex items-center gap-6 mb-6 px-4 py-2.5 border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          {[
            { label: "total", value: statsData.total, color: "" },
            { label: "queries", value: statsData.queries, color: "text-[var(--color-success)]" },
            { label: "executions", value: statsData.executions, color: "text-blue-400" },
            { label: "blocked", value: statsData.blocked, color: statsData.blocked > 0 ? "text-[var(--color-error)]" : "" },
          ].map(s => (
            <div key={s.label} className="flex items-center gap-2">
              <span className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">{s.label}</span>
              <span className={`text-xs tabular-nums ${s.color}`}>{s.value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6">
        <div className="flex items-center gap-2 flex-1">
          <Filter className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
          <input
            type="text"
            placeholder="search sql, connection, or reason..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="flex-1 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
          />
        </div>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
        >
          <option value="">all types</option>
          <option value="query">queries</option>
          <option value="execute">executions</option>
          <option value="connect">connections</option>
          <option value="block">blocked</option>
        </select>
        {!loading && (
          <span className="text-[10px] text-[var(--color-text-dim)] tabular-nums whitespace-nowrap tracking-wider">
            {filtered.length} entries
          </span>
        )}
      </div>

      {/* Table */}
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[var(--color-border)]">
              {["time", "type", "connection", "detail", "duration"].map((h, i) => (
                <th key={h} className={`${i === 4 ? "text-right" : "text-left"} px-4 py-2.5 text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-border)]">
            {loading && filtered.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center">
                  <Loader2 className="w-4 h-4 animate-spin mx-auto text-[var(--color-text-dim)]" />
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={5}>
                  <EmptyState
                    icon={EmptyList}
                    title="no entries found"
                    description="run some queries to populate the audit log"
                  />
                </td>
              </tr>
            ) : (
              filtered.map((entry) => {
                const Icon = typeIcons[entry.event_type] || ScrollText;
                const color = typeColors[entry.event_type] || typeColors.connect;
                const isExpanded = expandedRow === entry.id;
                return (
                  <tr
                    key={entry.id}
                    onClick={() => setExpandedRow(isExpanded ? null : entry.id)}
                    className="hover:bg-[var(--color-bg-hover)] transition-colors cursor-pointer group"
                  >
                    <td className="px-4 py-2.5 text-[10px] text-[var(--color-text-dim)] tabular-nums whitespace-nowrap tracking-wider align-top">
                      <div className="flex items-center gap-1.5">
                        {isExpanded ? (
                          <ChevronDown className="w-2.5 h-2.5 text-[var(--color-text-dim)]" />
                        ) : (
                          <ChevronRight className="w-2.5 h-2.5 text-[var(--color-text-dim)] opacity-0 group-hover:opacity-100 transition-opacity" />
                        )}
                        {new Date(entry.timestamp * 1000).toLocaleString()}
                      </div>
                      {isExpanded && entry.sql && (
                        <div className="mt-3 ml-4 animate-fade-in">
                          <p className="text-[9px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-1">full sql</p>
                          <pre className="whitespace-pre-wrap text-[11px] text-[var(--color-text-muted)] bg-[var(--color-bg)] p-3 border border-[var(--color-border)] max-h-40 overflow-auto">
                            {entry.sql}
                          </pre>
                          {entry.rows_returned != null && (
                            <p className="text-[9px] text-[var(--color-text-dim)] mt-2 tracking-wider">
                              rows: <span className="text-[var(--color-text-muted)] tabular-nums">{entry.rows_returned.toLocaleString()}</span>
                            </p>
                          )}
                          {entry.metadata && Object.keys(entry.metadata).length > 0 && (
                            <div className="mt-2">
                              <p className="text-[9px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-1">metadata</p>
                              <pre className="text-[9px] text-[var(--color-text-dim)] bg-[var(--color-bg)] p-2 border border-[var(--color-border)]">
                                {JSON.stringify(entry.metadata, null, 2)}
                              </pre>
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2.5 align-top">
                      <span className={`flex items-center gap-1.5 text-[10px] tracking-wider ${color}`}>
                        <Icon className="w-3 h-3" strokeWidth={1.5} />
                        {entry.event_type}
                        {entry.blocked && (
                          <span className="px-1 py-0.5 border badge-error text-[9px] uppercase tracking-wider">
                            blocked
                          </span>
                        )}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-[10px] text-[var(--color-text-dim)] align-top tracking-wider">
                      {entry.connection_name || "—"}
                    </td>
                    <td className="px-4 py-2.5 max-w-md align-top">
                      {entry.sql ? (
                        <code className="text-[10px] text-[var(--color-text-muted)] bg-[var(--color-bg)] px-2 py-0.5 block truncate">
                          {entry.sql}
                        </code>
                      ) : entry.block_reason ? (
                        <span className="text-[10px] text-[var(--color-error)]">{entry.block_reason}</span>
                      ) : (
                        <span className="text-[10px] text-[var(--color-text-dim)]">
                          {entry.metadata?.code_preview ? String(entry.metadata.code_preview).slice(0, 60) : "—"}
                        </span>
                      )}
                      {entry.tables.length > 0 && (
                        <div className="flex gap-1 mt-1 flex-wrap">
                          {entry.tables.map((t) => (
                            <span key={t} className="text-[9px] px-1 py-0.5 border border-[var(--color-border)] text-[var(--color-text-dim)] tracking-wider">
                              {t}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-[10px] text-right tabular-nums text-[var(--color-text-dim)] whitespace-nowrap align-top tracking-wider">
                      {entry.duration_ms != null ? `${entry.duration_ms.toFixed(0)}ms` : "—"}
                      {entry.rows_returned != null && (
                        <div className="text-[9px] text-[var(--color-text-dim)] mt-0.5">{entry.rows_returned}r</div>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
