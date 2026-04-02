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
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { ActivityDots, StatusDot, Sparkline } from "@/components/ui/data-viz";
import { SqlHighlight } from "@/components/ui/sql-highlight";
import { TimeAgo } from "@/components/ui/time-ago";

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

  // Compute activity density for heatmap (36 time slots from entries)
  const activitySlots = (() => {
    if (entries.length === 0) return [];
    const slots = new Array(36).fill(0);
    const timestamps = entries.map(e => e.timestamp).sort();
    const minTs = timestamps[0];
    const maxTs = timestamps[timestamps.length - 1];
    const range = maxTs - minTs || 1;
    entries.forEach(e => {
      const idx = Math.min(35, Math.floor(((e.timestamp - minTs) / range) * 35));
      slots[idx]++;
    });
    return slots;
  })();

  return (
    <div className="p-4 sm:p-8 animate-fade-in">
      <PageHeader
        title="audit"
        subtitle="log"
        description="full-chain audit trail of all governed operations"
        actions={<>

        <div className="flex flex-wrap items-center gap-2">
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
        </>}
      />

      <TerminalBar
        path="audit --tail -f"
        status={<StatusDot status={entries.length > 0 ? "healthy" : "unknown"} size={4} pulse={loading} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">events: <code className="text-[10px] text-[var(--color-text)]">{entries.length}</code></span>
          {statsData.blocked > 0 && <span className="text-[var(--color-error)]">blocked: <code className="text-[10px]">{statsData.blocked}</code></span>}
        </div>
      </TerminalBar>

      {/* Stats bar */}
      {entries.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 sm:gap-6 mb-6 px-4 py-2.5 border border-[var(--color-border)] bg-[var(--color-bg-card)]">
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
          {/* Latency sparkline from recent entries */}
          {(() => {
            const latencyVals = filtered
              .filter(e => e.duration_ms != null)
              .slice(0, 30)
              .map(e => e.duration_ms || 0)
              .reverse();
            if (latencyVals.length < 3) return null;
            const avg = latencyVals.reduce((a, b) => a + b, 0) / latencyVals.length;
            return (
              <div className="flex items-center gap-2 ml-auto">
                <span className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">latency</span>
                <Sparkline values={latencyVals} color="var(--color-success)" width={60} height={16} />
                <span className="text-[9px] tabular-nums text-[var(--color-text-dim)]">avg {avg.toFixed(0)}ms</span>
              </div>
            );
          })()}
          {activitySlots.length > 0 && (
            <div className={`flex items-center gap-2 ${filtered.filter(e => e.duration_ms != null).length < 3 ? "ml-auto" : ""}`}>
              <span className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">activity</span>
              <ActivityDots values={activitySlots} rows={3} cols={12} dotSize={5} gap={2} />
            </div>
          )}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <div className="flex items-center gap-2 flex-1 min-w-[200px]">
          <Filter className="w-3.5 h-3.5 text-[var(--color-text-dim)] flex-shrink-0" strokeWidth={1.5} />
          <input
            type="text"
            placeholder="search sql, connection, or reason..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="flex-1 px-3 py-2.5 sm:py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
          />
        </div>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="px-3 py-2.5 sm:py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
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
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-x-auto">
        <table className="w-full text-xs min-w-[640px]">
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
                    className="table-row-hover cursor-pointer group"
                  >
                    <td className="px-4 py-2.5 text-[10px] text-[var(--color-text-dim)] tabular-nums whitespace-nowrap tracking-wider align-top">
                      <div className="flex items-center gap-1.5">
                        {isExpanded ? (
                          <ChevronDown className="w-2.5 h-2.5 text-[var(--color-text-dim)]" />
                        ) : (
                          <ChevronRight className="w-2.5 h-2.5 text-[var(--color-text-dim)] sm:opacity-0 sm:group-hover:opacity-100 transition-opacity" />
                        )}
                        <TimeAgo timestamp={entry.timestamp} live className="text-[10px]" />
                      </div>
                      {isExpanded && entry.sql && (
                        <div className="mt-3 ml-4 animate-fade-in">
                          <p className="text-[9px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-1">full sql</p>
                          <pre className="text-[11px] bg-[var(--color-bg)] p-3 border border-[var(--color-border)] max-h-40 overflow-auto">
                            <SqlHighlight sql={entry.sql!} className="text-[11px]" />
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
                        <div className="text-[10px] bg-[var(--color-bg)] px-2 py-0.5 block truncate overflow-hidden">
                          <SqlHighlight sql={entry.sql.slice(0, 120)} className="text-[10px]" />
                        </div>
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
                    <td className="px-4 py-2.5 text-[10px] text-right tabular-nums whitespace-nowrap align-top tracking-wider">
                      {entry.duration_ms != null ? (
                        <span className={
                          entry.duration_ms < 50 ? "text-[var(--color-success)]" :
                          entry.duration_ms < 200 ? "text-[var(--color-text-dim)]" :
                          entry.duration_ms < 1000 ? "text-[var(--color-warning)]" :
                          "text-[var(--color-error)]"
                        }>
                          {entry.duration_ms.toFixed(0)}ms
                        </span>
                      ) : (
                        <span className="text-[var(--color-text-dim)]">—</span>
                      )}
                      {entry.rows_returned != null && (
                        <div className="text-[9px] text-[var(--color-text-dim)] mt-0.5">{entry.rows_returned.toLocaleString()}r</div>
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
