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
} from "lucide-react";
import { subscribeMetrics, getAudit } from "@/lib/api";
import type { MetricsSnapshot, AuditEntry } from "@/lib/types";

function MetricCard({
  label,
  value,
  icon: Icon,
  color = "var(--color-accent)",
}: {
  label: string;
  value: string | number;
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

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [recentAudit, setRecentAudit] = useState<AuditEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const unsub = subscribeMetrics((data) => {
      setMetrics(data);
      setError(null);
    });

    getAudit({ limit: 20 })
      .then((res) => setRecentAudit(res.entries))
      .catch(() => {});

    return unsub;
  }, []);

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold mb-1">Dashboard</h1>
        <p className="text-sm text-[var(--color-text-muted)]">
          Live overview of your SignalPilot instance
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
          <span className="text-sm text-[var(--color-text-muted)]">Shuru:</span>
          <StatusBadge ok={metrics ? metrics.shuru_available : null} />
        </div>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <MetricCard
          label="Active Sandboxes"
          value={metrics?.active_sandboxes ?? "—"}
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
          value={metrics?.connections ?? "—"}
          icon={Database}
          color="var(--color-success)"
        />
        <MetricCard
          label="Running Sandboxes"
          value={metrics?.running_sandboxes ?? "—"}
          icon={Activity}
          color="#8b5cf6"
        />
      </div>

      {/* Recent activity */}
      <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--color-border)]">
          <h2 className="text-sm font-medium">Recent Activity</h2>
          <a href="/audit" className="text-xs text-[var(--color-accent)] hover:underline">
            View all
          </a>
        </div>
        <div className="divide-y divide-[var(--color-border)]">
          {recentAudit.length === 0 ? (
            <div className="px-5 py-12 text-center text-sm text-[var(--color-text-dim)]">
              No activity yet. Create a sandbox to get started.
            </div>
          ) : (
            recentAudit.slice(0, 10).map((entry) => (
              <div
                key={entry.id}
                className="flex items-center gap-4 px-5 py-3 hover:bg-[var(--color-bg-hover)] transition-colors"
              >
                <div
                  className={`w-2 h-2 rounded-full ${
                    entry.blocked
                      ? "bg-[var(--color-error)]"
                      : entry.event_type === "execute"
                        ? "bg-[var(--color-accent)]"
                        : entry.event_type === "query"
                          ? "bg-[var(--color-success)]"
                          : "bg-[var(--color-text-dim)]"
                  }`}
                />
                <span className="text-xs uppercase font-medium text-[var(--color-text-muted)] w-16">
                  {entry.event_type}
                </span>
                <span className="flex-1 text-sm truncate text-[var(--color-text)]">
                  {entry.sql
                    ? entry.sql.slice(0, 80)
                    : entry.metadata?.code_preview
                      ? String(entry.metadata.code_preview).slice(0, 80)
                      : entry.connection_name || "—"}
                </span>
                {entry.blocked && (
                  <span className="text-xs px-2 py-0.5 rounded bg-[var(--color-error)]/10 text-[var(--color-error)]">
                    blocked
                  </span>
                )}
                {entry.duration_ms != null && (
                  <span className="text-xs tabular-nums text-[var(--color-text-dim)]">
                    {entry.duration_ms.toFixed(0)}ms
                  </span>
                )}
                <span className="text-xs text-[var(--color-text-dim)] w-16 text-right">
                  {timeAgo(entry.timestamp)}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
