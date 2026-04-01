"use client";

import { useEffect, useState } from "react";
import {
  Terminal,
  Database,
  Activity,
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
import { subscribeMetrics, getAudit, getBudgets, getConnections } from "@/lib/api";
import type { MetricsSnapshot, AuditEntry, ConnectionInfo } from "@/lib/types";

function MetricCard({
  label,
  value,
  subtext,
  icon: Icon,
  color = "var(--color-accent)",
}: {
  label: string;
  value: string | number;
  subtext?: string;
  icon: React.ElementType;
  color?: string;
}) {
  return (
    <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl p-5">
      <div className="flex items-center gap-3 mb-3">
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center"
          style={{ backgroundColor: `${color}15` }}
        >
          <Icon className="w-4 h-4" style={{ color }} />
        </div>
        <span className="text-sm text-[var(--color-text-muted)]">{label}</span>
      </div>
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      {subtext && (
        <p className="text-xs text-[var(--color-text-dim)] mt-1">{subtext}</p>
      )}
    </div>
  );
}

function StatusBadge({ ok }: { ok: boolean | null }) {
  if (ok === null) return <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--color-text-muted)]" />;
  return ok ? (
    <span className="flex items-center gap-1 text-xs text-[var(--color-success)]">
      <CheckCircle2 className="w-3.5 h-3.5" /> Healthy
    </span>
  ) : (
    <span className="flex items-center gap-1 text-xs text-[var(--color-error)]">
      <XCircle className="w-3.5 h-3.5" /> Offline
    </span>
  );
}

function timeAgo(ts: number): string {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

const eventTypeConfig: Record<string, { color: string; label: string }> = {
  query: { color: "bg-[var(--color-success)]", label: "QUERY" },
  execute: { color: "bg-[var(--color-accent)]", label: "EXEC" },
  connect: { color: "bg-blue-500", label: "CONN" },
  block: { color: "bg-[var(--color-error)]", label: "BLOCK" },
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

  useEffect(() => {
    const unsub = subscribeMetrics((data) => {
      setMetrics(data);
    });

    getAudit({ limit: 50 })
      .then((res) => {
        setRecentAudit(res.entries);
        // Compute stats
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

    return unsub;
  }, []);

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-semibold mb-1">Dashboard</h1>
        <p className="text-sm text-[var(--color-text-muted)]">
          Live overview of your SignalPilot gateway
        </p>
      </div>

      {/* Status bar */}
      <div className="flex items-center gap-6 mb-6 p-4 bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl">
        <div className="flex items-center gap-2">
          <Server className="w-4 h-4 text-[var(--color-text-muted)]" />
          <span className="text-sm text-[var(--color-text-muted)]">Sandbox Manager:</span>
          <code className="text-xs text-[var(--color-text)] bg-[var(--color-bg)] px-2 py-0.5 rounded">
            {metrics?.sandbox_manager || "—"}
          </code>
          <StatusBadge ok={metrics ? metrics.sandbox_health === "healthy" : null} />
        </div>
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-[var(--color-text-muted)]" />
          <span className="text-sm text-[var(--color-text-muted)]">KVM:</span>
          <StatusBadge ok={metrics ? metrics.kvm_available : null} />
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Shield className="w-4 h-4 text-[var(--color-success)]" />
          <span className="text-xs text-[var(--color-text-muted)]">
            Governance: Active
          </span>
        </div>
      </div>

      {/* Metric cards — top row */}
      <div className="grid grid-cols-4 gap-4 mb-4">
        <MetricCard
          label="Active Sandboxes"
          value={metrics?.active_sandboxes ?? "—"}
          subtext={metrics ? `${metrics.running_sandboxes} running` : undefined}
          icon={Terminal}
        />
        <MetricCard
          label="Active VMs"
          value={metrics ? `${metrics.active_vms} / ${metrics.max_vms}` : "—"}
          icon={Cpu}
          color="var(--color-warning)"
        />
        <MetricCard
          label="Connections"
          value={connections.length}
          subtext={connections.length > 0 ? connections.map(c => c.db_type).filter((v, i, a) => a.indexOf(v) === i).join(", ") : undefined}
          icon={Database}
          color="var(--color-success)"
        />
        <MetricCard
          label="Total Spent"
          value={budgetData ? `$${budgetData.total_spent_usd.toFixed(4)}` : "$0.00"}
          subtext={budgetData ? `${budgetData.sessions.length} active sessions` : undefined}
          icon={DollarSign}
          color="#8b5cf6"
        />
      </div>

      {/* Stats cards — second row */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <MetricCard
          label="Queries Executed"
          value={auditStats.queries}
          icon={BarChart3}
          color="var(--color-success)"
        />
        <MetricCard
          label="Code Executions"
          value={auditStats.executions}
          icon={Zap}
          color="var(--color-accent)"
        />
        <MetricCard
          label="Blocked Queries"
          value={auditStats.blocks}
          icon={Shield}
          color="var(--color-error)"
        />
        <MetricCard
          label="Avg Duration"
          value={
            recentAudit.filter(e => e.duration_ms != null).length > 0
              ? `${Math.round(recentAudit.filter(e => e.duration_ms != null).reduce((sum, e) => sum + (e.duration_ms || 0), 0) / recentAudit.filter(e => e.duration_ms != null).length)}ms`
              : "—"
          }
          icon={Clock}
          color="var(--color-warning)"
        />
      </div>

      {/* Two-column layout: Activity + Connections */}
      <div className="grid grid-cols-3 gap-4">
        {/* Recent activity — takes 2 cols */}
        <div className="col-span-2 bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl">
          <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--color-border)]">
            <h2 className="text-sm font-medium">Recent Activity</h2>
            <a href="/audit" className="text-xs text-[var(--color-accent)] hover:underline">
              View all
            </a>
          </div>
          <div className="divide-y divide-[var(--color-border)]">
            {recentAudit.length === 0 ? (
              <div className="px-5 py-12 text-center text-sm text-[var(--color-text-dim)]">
                No activity yet. Connect a database and run a query to get started.
              </div>
            ) : (
              recentAudit.slice(0, 12).map((entry) => {
                const cfg = eventTypeConfig[entry.event_type] || eventTypeConfig.query;
                return (
                  <div
                    key={entry.id}
                    className="flex items-center gap-4 px-5 py-3 hover:bg-[var(--color-bg-hover)] transition-colors"
                  >
                    <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
                      entry.blocked ? "bg-[var(--color-error)]" : cfg.color
                    }`} />
                    <span className="text-[10px] uppercase font-semibold text-[var(--color-text-muted)] w-12">
                      {cfg.label}
                    </span>
                    <span className="flex-1 text-sm truncate text-[var(--color-text)]">
                      {entry.sql
                        ? entry.sql.slice(0, 80)
                        : entry.metadata?.code_preview
                          ? String(entry.metadata.code_preview).slice(0, 80)
                          : entry.connection_name || "—"}
                    </span>
                    {entry.blocked && (
                      <span className="text-[10px] px-2 py-0.5 rounded bg-[var(--color-error)]/10 text-[var(--color-error)] font-medium">
                        BLOCKED
                      </span>
                    )}
                    {entry.rows_returned != null && (
                      <span className="text-xs tabular-nums text-[var(--color-text-dim)]">
                        {entry.rows_returned} rows
                      </span>
                    )}
                    {entry.duration_ms != null && (
                      <span className="text-xs tabular-nums text-[var(--color-text-dim)]">
                        {entry.duration_ms.toFixed(0)}ms
                      </span>
                    )}
                    <span className="text-xs text-[var(--color-text-dim)] w-16 text-right flex-shrink-0">
                      {timeAgo(entry.timestamp)}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Connections overview — 1 col */}
        <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl">
          <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--color-border)]">
            <h2 className="text-sm font-medium">Connections</h2>
            <a href="/connections" className="text-xs text-[var(--color-accent)] hover:underline">
              Manage
            </a>
          </div>
          <div className="divide-y divide-[var(--color-border)]">
            {connections.length === 0 ? (
              <div className="px-5 py-12 text-center">
                <Database className="w-8 h-8 mx-auto mb-2 text-[var(--color-text-dim)] opacity-30" />
                <p className="text-xs text-[var(--color-text-dim)]">
                  No connections yet
                </p>
              </div>
            ) : (
              connections.map((conn) => (
                <div
                  key={conn.id}
                  className="flex items-center gap-3 px-5 py-3 hover:bg-[var(--color-bg-hover)] transition-colors"
                >
                  <span className="text-lg">
                    {conn.db_type === "postgres"
                      ? "🐘"
                      : conn.db_type === "duckdb"
                        ? "🦆"
                        : conn.db_type === "mysql"
                          ? "🐬"
                          : "❄️"}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{conn.name}</p>
                    <p className="text-xs text-[var(--color-text-dim)] truncate">
                      {conn.host}:{conn.port}/{conn.database}
                    </p>
                  </div>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-[var(--color-bg)] text-[var(--color-text-muted)]">
                    {conn.db_type}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
