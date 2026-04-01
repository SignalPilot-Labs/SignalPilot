"use client";

import { useEffect, useState } from "react";
import {
  Terminal,
  Database,
  Cpu,
  Server,
  CheckCircle2,
  XCircle,
  Loader2,
  Shield,
  DollarSign,
  Clock,
  Zap,
  BarChart3,
} from "lucide-react";
import { subscribeMetrics, getAudit, getBudgets, getConnections, getCacheStats, getConnectionsHealth } from "@/lib/api";
import type { MetricsSnapshot, AuditEntry, ConnectionInfo, ConnectionHealthStats } from "@/lib/types";
import { GovernancePipeline } from "@/components/ui/governance-pipeline";

function MetricCard({
  label,
  value,
  subtext,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  subtext?: string;
  icon: React.ElementType;
}) {
  return (
    <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] p-5 hover:border-[var(--color-border-hover)] transition-colors">
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
        <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-widest">{label}</span>
      </div>
      <p className="text-xl font-light tabular-nums text-[var(--color-text)]">{value}</p>
      {subtext && (
        <p className="text-[10px] text-[var(--color-text-dim)] mt-1 tracking-wider">{subtext}</p>
      )}
    </div>
  );
}

function StatusBadge({ ok }: { ok: boolean | null }) {
  if (ok === null) return <Loader2 className="w-3 h-3 animate-spin text-[var(--color-text-dim)]" />;
  return ok ? (
    <span className="flex items-center gap-1.5 text-[10px] text-[var(--color-success)] tracking-wider">
      <span className="w-1.5 h-1.5 bg-[var(--color-success)] pulse-dot" />
      healthy
    </span>
  ) : (
    <span className="flex items-center gap-1.5 text-[10px] text-[var(--color-error)] tracking-wider">
      <span className="w-1.5 h-1.5 bg-[var(--color-error)]" />
      offline
    </span>
  );
}

function timeAgo(ts: number): string {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return `${Math.floor(diff)}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

const eventTypeConfig: Record<string, { label: string }> = {
  query: { label: "QRY" },
  execute: { label: "EXE" },
  connect: { label: "CON" },
  block: { label: "BLK" },
};

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [recentAudit, setRecentAudit] = useState<AuditEntry[]>([]);
  const [budgetData, setBudgetData] = useState<{
    sessions: Record<string, unknown>[];
    total_spent_usd: number;
  } | null>(null);
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [auditStats, setAuditStats] = useState({
    queries: 0,
    executions: 0,
    blocks: 0,
    total: 0,
  });
  const [cacheStats, setCacheStats] = useState<{
    entries: number;
    max_entries: number;
    hits: number;
    misses: number;
    hit_rate: number;
  } | null>(null);
  const [connHealth, setConnHealth] = useState<Record<string, ConnectionHealthStats>>({});

  useEffect(() => {
    const unsub = subscribeMetrics((data) => {
      setMetrics(data);
    });

    getAudit({ limit: 50 })
      .then((res) => {
        setRecentAudit(res.entries);
        const stats = { queries: 0, executions: 0, blocks: 0, total: res.entries.length };
        for (const e of res.entries) {
          if (e.event_type === "query") stats.queries++;
          else if (e.event_type === "execute") stats.executions++;
          if (e.blocked) stats.blocks++;
        }
        setAuditStats(stats);
      })
      .catch(() => {});

    getBudgets().then(setBudgetData).catch(() => {});
    getConnections().then(setConnections).catch(() => {});
    getCacheStats().then(setCacheStats).catch(() => {});
    getConnectionsHealth()
      .then((res) => {
        const map: Record<string, ConnectionHealthStats> = {};
        for (const h of res.connections) {
          map[h.connection_name] = h;
        }
        setConnHealth(map);
      })
      .catch(() => {});

    return unsub;
  }, []);

  return (
    <div className="p-8 max-w-[1400px]">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-1">
          <h1 className="text-lg font-light tracking-wide text-[var(--color-text)]">dashboard</h1>
          <span className="text-[9px] text-[var(--color-text-dim)] tracking-widest uppercase">/ live overview</span>
        </div>
        <p className="text-xs text-[var(--color-text-dim)] tracking-wider">
          signalpilot gateway status and metrics
        </p>
      </div>

      {/* Status bar — terminal-style */}
      <div className="mb-6 border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        <div className="px-4 py-2 border-b border-[var(--color-border)] flex items-center gap-2">
          <span className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-widest">system status</span>
        </div>
        <div className="px-4 py-3 flex items-center gap-8 text-xs">
          <div className="flex items-center gap-2">
            <Server className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[var(--color-text-dim)]">sandbox_mgr:</span>
            <code className="text-[10px] text-[var(--color-text)]">
              {metrics?.sandbox_manager || "—"}
            </code>
            <StatusBadge ok={metrics ? metrics.sandbox_health === "healthy" : null} />
          </div>
          <div className="flex items-center gap-2">
            <Cpu className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[var(--color-text-dim)]">kvm:</span>
            <StatusBadge ok={metrics ? metrics.kvm_available : null} />
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Shield className="w-3 h-3 text-[var(--color-success)]" strokeWidth={1.5} />
            <span className="text-[10px] text-[var(--color-text-dim)] tracking-wider">
              governance: active
            </span>
          </div>
        </div>
      </div>

      {/* Metric cards — top row */}
      <div className="grid grid-cols-4 gap-px mb-px bg-[var(--color-border)]">
        <MetricCard
          label="active sandboxes"
          value={metrics?.active_sandboxes ?? "—"}
          subtext={metrics ? `${metrics.running_sandboxes} running` : undefined}
          icon={Terminal}
        />
        <MetricCard
          label="active vms"
          value={metrics ? `${metrics.active_vms} / ${metrics.max_vms}` : "—"}
          icon={Cpu}
        />
        <MetricCard
          label="connections"
          value={connections.length}
          subtext={connections.length > 0 ? connections.map(c => c.db_type).filter((v, i, a) => a.indexOf(v) === i).join(", ") : undefined}
          icon={Database}
        />
        <MetricCard
          label="total spent"
          value={budgetData ? `$${budgetData.total_spent_usd.toFixed(4)}` : "$0.00"}
          subtext={budgetData ? `${budgetData.sessions.length} sessions` : undefined}
          icon={DollarSign}
        />
      </div>

      {/* Stats cards — second row */}
      <div className="grid grid-cols-4 gap-px mb-8 bg-[var(--color-border)]">
        <MetricCard
          label="queries"
          value={auditStats.queries}
          icon={BarChart3}
        />
        <MetricCard
          label="executions"
          value={auditStats.executions}
          icon={Zap}
        />
        <MetricCard
          label="blocked"
          value={auditStats.blocks}
          icon={Shield}
        />
        <MetricCard
          label="avg latency"
          value={
            recentAudit.filter(e => e.duration_ms != null).length > 0
              ? `${Math.round(recentAudit.filter(e => e.duration_ms != null).reduce((sum, e) => sum + (e.duration_ms || 0), 0) / recentAudit.filter(e => e.duration_ms != null).length)}ms`
              : "—"
          }
          icon={Clock}
        />
      </div>

      {/* Governance Pipeline */}
      <div className="mb-8">
        <GovernancePipeline />
      </div>

      {/* Two-column layout: Activity + Connections */}
      <div className="grid grid-cols-3 gap-4">
        {/* Recent activity — takes 2 cols */}
        <div className="col-span-2 border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
            <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-widest">
              recent activity
            </span>
            <a href="/audit" className="text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider">
              view all &rarr;
            </a>
          </div>
          <div className="divide-y divide-[var(--color-border)]">
            {recentAudit.length === 0 ? (
              <div className="px-4 py-12 text-center text-xs text-[var(--color-text-dim)]">
                <Terminal className="w-5 h-5 mx-auto mb-2 opacity-30" strokeWidth={1} />
                no activity yet. connect a database to get started.
              </div>
            ) : (
              recentAudit.slice(0, 12).map((entry) => {
                const cfg = eventTypeConfig[entry.event_type] || eventTypeConfig.query;
                return (
                  <div
                    key={entry.id}
                    className="flex items-center gap-3 px-4 py-2.5 hover:bg-[var(--color-bg-hover)] transition-colors"
                  >
                    <span className={`text-[9px] font-medium uppercase tracking-widest w-8 ${
                      entry.blocked ? "text-[var(--color-error)]" : "text-[var(--color-text-dim)]"
                    }`}>
                      {cfg.label}
                    </span>
                    <span className="flex-1 text-xs truncate text-[var(--color-text-muted)]">
                      {entry.sql
                        ? entry.sql.slice(0, 80)
                        : entry.metadata?.code_preview
                          ? String(entry.metadata.code_preview).slice(0, 80)
                          : entry.connection_name || "—"}
                    </span>
                    {entry.blocked && (
                      <span className="text-[9px] px-1.5 py-0.5 border border-[var(--color-error)]/30 text-[var(--color-error)] tracking-wider uppercase">
                        blocked
                      </span>
                    )}
                    {entry.rows_returned != null && (
                      <span className="text-[10px] tabular-nums text-[var(--color-text-dim)]">
                        {entry.rows_returned}r
                      </span>
                    )}
                    {entry.duration_ms != null && (
                      <span className="text-[10px] tabular-nums text-[var(--color-text-dim)]">
                        {entry.duration_ms.toFixed(0)}ms
                      </span>
                    )}
                    <span className="text-[10px] text-[var(--color-text-dim)] w-10 text-right flex-shrink-0 tabular-nums">
                      {timeAgo(entry.timestamp)}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right column — Connections + Cache */}
        <div className="space-y-4">
          {/* Connections overview */}
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
              <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-widest">
                connections
              </span>
              <a href="/connections" className="text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider">
                manage &rarr;
              </a>
            </div>
            <div className="divide-y divide-[var(--color-border)]">
              {connections.length === 0 ? (
                <div className="px-4 py-10 text-center">
                  <Database className="w-5 h-5 mx-auto mb-2 text-[var(--color-text-dim)] opacity-20" strokeWidth={1} />
                  <p className="text-[10px] text-[var(--color-text-dim)] tracking-wider">
                    no connections
                  </p>
                </div>
              ) : (
                connections.map((conn) => {
                  const health = connHealth[conn.name];
                  return (
                    <div
                      key={conn.id}
                      className="flex items-center gap-3 px-4 py-2.5 hover:bg-[var(--color-bg-hover)] transition-colors"
                    >
                      <span className={`w-1.5 h-1.5 flex-shrink-0 ${
                        health?.status === "healthy" ? "bg-[var(--color-success)]" :
                        health?.status === "warning" ? "bg-[var(--color-warning)]" :
                        health?.status === "degraded" || health?.status === "unhealthy" ? "bg-[var(--color-error)]" :
                        "bg-[var(--color-text-dim)]"
                      }`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs text-[var(--color-text-muted)] truncate">{conn.name}</p>
                        <p className="text-[10px] text-[var(--color-text-dim)] truncate">
                          {conn.host}:{conn.port}/{conn.database}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        {health?.latency_p50_ms != null && (
                          <span className="text-[10px] tabular-nums text-[var(--color-text-dim)]">
                            {health.latency_p50_ms.toFixed(0)}ms
                          </span>
                        )}
                        <span className="text-[9px] px-1.5 py-0.5 border border-[var(--color-border)] text-[var(--color-text-dim)] tracking-wider">
                          {conn.db_type}
                        </span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Query Cache Stats */}
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
            <div className="px-4 py-3 border-b border-[var(--color-border)]">
              <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-widest">
                query cache
              </span>
            </div>
            <div className="p-4 space-y-3">
              {cacheStats ? (
                <>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-[var(--color-text-dim)] tracking-wider">hit_rate</span>
                    <span className="text-xs font-light tabular-nums text-[var(--color-text)]">
                      {(cacheStats.hit_rate * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="w-full h-1 bg-[var(--color-bg)] overflow-hidden">
                    <div
                      className="h-full bg-[var(--color-success)] transition-all"
                      style={{ width: `${cacheStats.hit_rate * 100}%` }}
                    />
                  </div>
                  <div className="grid grid-cols-3 gap-3 pt-1">
                    <div>
                      <p className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-widest">hits</p>
                      <p className="text-xs font-light tabular-nums text-[var(--color-success)]">{cacheStats.hits}</p>
                    </div>
                    <div>
                      <p className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-widest">miss</p>
                      <p className="text-xs font-light tabular-nums text-[var(--color-text-muted)]">{cacheStats.misses}</p>
                    </div>
                    <div>
                      <p className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-widest">size</p>
                      <p className="text-xs font-light tabular-nums">{cacheStats.entries}/{cacheStats.max_entries}</p>
                    </div>
                  </div>
                </>
              ) : (
                <p className="text-[10px] text-[var(--color-text-dim)]">loading...</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
