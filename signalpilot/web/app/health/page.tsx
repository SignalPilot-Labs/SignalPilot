"use client";

import { useState } from "react";
import { mutate } from "swr";
import {
  Activity,
  RefreshCw,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Database,
  TrendingUp,
  Wifi,
  WifiOff,
  Zap,
  BarChart3,
} from "lucide-react";
import {
  getConnectionHealth,
  testConnection,
} from "@/lib/api";
import {
  useConnections,
  useConnectionsHealth,
  useSchemaCache,
  SWR_KEYS,
} from "@/lib/hooks/use-gateway-data";
import type { ConnectionHealthStats, ConnectionInfo } from "@/lib/types";
import { EmptyChart, EmptyState } from "@/components/ui/empty-states";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { PageLoader } from "@/components/ui/page-loader";
import { RingGauge, StatusDot, Sparkline, MiniBar } from "@/components/ui/data-viz";
import { Tooltip } from "@/components/ui/tooltip";
import { TimeAgo } from "@/components/ui/time-ago";

const statusConfig: Record<string, { color: string; bg: string; icon: React.ElementType; label: string }> = {
  healthy: { color: "text-[var(--color-success)]", bg: "bg-[var(--color-success)]", icon: CheckCircle2, label: "healthy" },
  warning: { color: "text-[var(--color-warning)]", bg: "bg-[var(--color-warning)]", icon: AlertTriangle, label: "warning" },
  degraded: { color: "text-orange-400", bg: "bg-orange-400", icon: AlertTriangle, label: "degraded" },
  unhealthy: { color: "text-[var(--color-error)]", bg: "bg-[var(--color-error)]", icon: XCircle, label: "unhealthy" },
  unknown: { color: "text-[var(--color-text-dim)]", bg: "bg-[var(--color-text-dim)]", icon: Activity, label: "unknown" },
};

/* ── Latency bar with SVG visualization ── */
function LatencyBar({ label, value, maxMs = 500 }: { label: string; value: number | null | undefined; maxMs?: number }) {
  if (value == null) return null;
  const pct = Math.min(100, (value / maxMs) * 100);
  const color = value < 50 ? "var(--color-success)" : value < 200 ? "var(--color-warning)" : "var(--color-error)";

  return (
    <Tooltip content={`${label}: ${value.toFixed(2)}ms (${pct.toFixed(0)}% of ${maxMs}ms budget)`} position="top">
      <div className="flex items-center gap-3 cursor-default">
        <span className="text-[11px] text-[var(--color-text-dim)] w-8 text-right uppercase tracking-[0.15em]">{label}</span>
        <div className="flex-1 h-1.5 bg-[var(--color-bg)] overflow-hidden relative">
          <div className="h-full transition-all duration-500" style={{ width: `${pct}%`, backgroundColor: color }} />
          {/* Threshold markers */}
          <div className="absolute top-0 h-full w-px bg-[var(--color-text-dim)] opacity-20" style={{ left: `${(50/maxMs)*100}%` }} />
          <div className="absolute top-0 h-full w-px bg-[var(--color-text-dim)] opacity-20" style={{ left: `${(200/maxMs)*100}%` }} />
        </div>
        <span className={`text-[12px] tabular-nums w-16 text-right tracking-wider ${
          value < 50 ? "text-[var(--color-success)]" : value < 200 ? "text-[var(--color-text-dim)]" : "text-[var(--color-error)]"
        }`}>{value.toFixed(1)}ms</span>
      </div>
    </Tooltip>
  );
}

/* ── Latency percentile distribution visualization ── */
function LatencyDistribution({ p50, p95, p99 }: { p50: number | null | undefined; p95: number | null | undefined; p99: number | null | undefined }) {
  const values = [p50, p95, p99].filter((v): v is number => v != null);
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);

  return (
    <div className="flex items-end gap-1 h-6">
      {[
        { label: "p50", value: p50, color: "var(--color-success)" },
        { label: "p95", value: p95, color: "var(--color-warning)" },
        { label: "p99", value: p99, color: "var(--color-error)" },
      ].map(({ label, value, color }) => {
        if (value == null) return null;
        const h = Math.max(4, (value / max) * 24);
        return (
          <Tooltip key={label} content={`${label}: ${value.toFixed(1)}ms`} position="top">
            <div className="flex flex-col items-center gap-0.5 cursor-default">
              <div className="w-3 transition-all duration-500" style={{ height: `${h}px`, backgroundColor: color, opacity: 0.7 }} />
              <span className="text-[7px] text-[var(--color-text-dim)] tracking-wider">{label}</span>
            </div>
          </Tooltip>
        );
      })}
    </div>
  );
}

export default function HealthPage() {
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { status: string; message: string }>>({});
  const [autoRefresh, setAutoRefresh] = useState(true);

  const { data: connectionsData, isLoading: connectionsLoading } = useConnections();
  const { data: healthRaw, isLoading: healthLoading, mutate: mutateHealth } = useConnectionsHealth(autoRefresh);
  const { data: schemaCache } = useSchemaCache();

  const connections = connectionsData ?? [];
  const healthData = healthRaw?.connections ?? [];
  const loading = connectionsLoading && healthLoading;

  function handleRefresh() {
    mutate(SWR_KEYS.connections);
    mutate(SWR_KEYS.connectionsHealth);
    mutate(SWR_KEYS.schemaCache);
  }

  async function handleTest(name: string) {
    setTesting(name);
    try {
      const result = await testConnection(name);
      setTestResults((prev) => ({ ...prev, [name]: result }));
      try {
        const h = await getConnectionHealth(name);
        mutateHealth((prev) => {
          if (!prev) return prev;
          return { ...prev, connections: prev.connections.map((item) => item.connection_name === name ? h : item) };
        }, false);
      } catch {}
    } catch (e) {
      setTestResults((prev) => ({ ...prev, [name]: { status: "error", message: String(e) } }));
    } finally { setTesting(null); }
  }

  const overallHealthy = healthData.filter((h) => h.status === "healthy").length;
  const overallTotal = healthData.length;
  const avgLatency = healthData.filter((h) => h.latency_avg_ms != null).length > 0
    ? healthData.reduce((sum, h) => sum + (h.latency_avg_ms || 0), 0) / healthData.filter((h) => h.latency_avg_ms != null).length
    : null;

  return (
    <div className="p-8 animate-fade-in">
      <PageHeader
        title="health"
        subtitle="monitoring"
        description="connection health, latency, and cache performance"
        actions={
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] cursor-pointer tracking-wider px-2 py-1.5 border border-[var(--color-border)] hover:border-[var(--color-border-hover)] transition-colors">
              <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} className="rounded-none" />
              auto (10s)
            </label>
            <button onClick={handleRefresh} disabled={loading}
              className="flex items-center gap-1.5 px-3 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider">
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} strokeWidth={1.5} />
              refresh
            </button>
          </div>
        }
      />

      <TerminalBar
        path="health --monitor"
        status={<StatusDot status={overallHealthy === overallTotal && overallTotal > 0 ? "healthy" : overallTotal > 0 ? "warning" : "unknown"} size={4} pulse={autoRefresh} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">nodes: <code className="text-[12px] text-[var(--color-text)]">{overallHealthy}/{overallTotal}</code></span>
          <span className="text-[var(--color-text-dim)]">refresh: <code className="text-[12px] text-[var(--color-text)]">{autoRefresh ? "10s" : "manual"}</code></span>
        </div>
      </TerminalBar>

      {/* Overview cards */}
      <div className="grid grid-cols-4 gap-px mb-8 bg-[var(--color-border)] stagger-fade-in">
        {/* Connections */}
        <div className="bg-[var(--color-bg-card)] p-5 hover:bg-[var(--color-bg-hover)] transition-colors card-accent-top">
          <div className="flex items-center gap-2 mb-3">
            <Wifi className={`w-3.5 h-3.5 ${overallHealthy === overallTotal && overallTotal > 0 ? "text-[var(--color-success)]" : "text-[var(--color-text-dim)]"}`} strokeWidth={1.5} />
            <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">connections</span>
          </div>
          <div className="flex items-center gap-3">
            <RingGauge
              value={overallHealthy}
              max={Math.max(overallTotal, 1)}
              size={32}
              strokeWidth={3}
              color={overallHealthy === overallTotal ? "var(--color-success)" : "var(--color-warning)"}
            />
            <div>
              <p className={`text-lg font-light tabular-nums ${overallHealthy === overallTotal && overallTotal > 0 ? "text-[var(--color-success)]" : ""}`}>{overallHealthy}/{overallTotal}</p>
              <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider">healthy</p>
            </div>
          </div>
        </div>
        {/* Avg Latency */}
        <div className="bg-[var(--color-bg-card)] p-5 hover:bg-[var(--color-bg-hover)] transition-colors card-accent-top">
          <div className="flex items-center gap-2 mb-3">
            <Clock className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">avg latency</span>
          </div>
          <p className="text-xl font-light tabular-nums">{avgLatency != null ? `${avgLatency.toFixed(1)}ms` : "--"}</p>
          <p className="text-[12px] text-[var(--color-text-dim)] mt-1 tracking-wider">all connections</p>
        </div>
        {/* Schema Cache */}
        <div className="bg-[var(--color-bg-card)] p-5 hover:bg-[var(--color-bg-hover)] transition-colors card-accent-top">
          <div className="flex items-center gap-2 mb-3">
            <Database className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">schema cache</span>
          </div>
          <p className="text-xl font-light tabular-nums">{schemaCache ? String(schemaCache.cached_connections) : "--"}</p>
          <p className="text-[12px] text-[var(--color-text-dim)] mt-1 tracking-wider">{schemaCache ? `${schemaCache.total_entries} entries, ttl ${schemaCache.ttl_seconds}s` : "cached connections"}</p>
        </div>
      </div>

      {/* Connection health cards */}
      {loading && healthData.length === 0 ? (
        <PageLoader label="loading health" />
      ) : healthData.length === 0 ? (
        <EmptyState
          icon={EmptyChart}
          title="no health data"
          description="connect a database and run queries to see health metrics"
        />
      ) : (
        <div className="space-y-4">
          <div className="section-header">
            <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">connection health</span>
          </div>
          <div className="grid grid-cols-2 gap-px bg-[var(--color-border)] stagger-fade-in">
            {healthData.map((health) => {
              const cfg = statusConfig[health.status] || statusConfig.unknown;
              const StatusIcon = cfg.icon;
              const conn = connections.find((c) => c.name === health.connection_name);
              const testResult = testResults[health.connection_name];

              return (
                <div key={health.connection_name} className="bg-[var(--color-bg-card)] overflow-hidden">
                  <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--color-border)]">
                    <div className="flex items-center gap-3">
                      <StatusDot
                        status={health.status === "healthy" ? "healthy" : health.status === "warning" || health.status === "degraded" ? "warning" : health.status === "unhealthy" ? "error" : "unknown"}
                        size={5}
                        pulse={health.status === "healthy"}
                      />
                      <div>
                        <h3 className="text-xs text-[var(--color-text)]">{health.connection_name}</h3>
                        <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
                          {health.db_type}{conn ? ` — ${conn.host}:${conn.port}` : ""}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`flex items-center gap-1 text-[12px] tracking-wider ${cfg.color}`}>
                        <StatusIcon className="w-3 h-3" strokeWidth={1.5} /> {cfg.label}
                      </span>
                      <button onClick={() => handleTest(health.connection_name)} disabled={testing === health.connection_name}
                        className="flex items-center gap-1 px-2 py-1 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-all disabled:opacity-50 tracking-wider">
                        {testing === health.connection_name ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <Activity className="w-2.5 h-2.5" strokeWidth={1.5} />}
                        test
                      </button>
                    </div>
                  </div>

                  <div className="px-5 py-4 space-y-4">
                    {/* Latency bars + distribution */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">latency</div>
                        <LatencyDistribution p50={health.latency_p50_ms} p95={health.latency_p95_ms} p99={health.latency_p99_ms} />
                      </div>
                      <LatencyBar label="p50" value={health.latency_p50_ms} />
                      <LatencyBar label="p95" value={health.latency_p95_ms} />
                      <LatencyBar label="p99" value={health.latency_p99_ms} />
                    </div>

                    {/* Stats grid */}
                    <div className="grid grid-cols-3 gap-3">
                      {[
                        { label: "samples", value: health.sample_count, color: "" },
                        { label: "success", value: health.successes ?? "--", color: "text-[var(--color-success)]" },
                        { label: "failures", value: health.failures ?? 0, color: "text-[var(--color-error)]" },
                      ].map((stat) => (
                        <div key={stat.label}>
                          <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">{stat.label}</p>
                          <p className={`text-xs font-light tabular-nums ${stat.color}`}>{stat.value}</p>
                        </div>
                      ))}
                      {health.error_rate != null && (
                        <div>
                          <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">error rate</p>
                          <p className={`text-xs font-light tabular-nums ${
                            health.error_rate > 0.1 ? "text-[var(--color-error)]" : health.error_rate > 0 ? "text-[var(--color-warning)]" : "text-[var(--color-success)]"
                          }`}>{(health.error_rate * 100).toFixed(1)}%</p>
                        </div>
                      )}
                      {health.consecutive_failures != null && health.consecutive_failures > 0 && (
                        <div>
                          <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">consec fails</p>
                          <p className="text-xs font-light tabular-nums text-[var(--color-error)]">{health.consecutive_failures}</p>
                        </div>
                      )}
                    </div>

                    {health.last_error && (
                      <div className="p-2.5 border border-[var(--color-error)]/20 bg-[var(--color-error)]/5">
                        <p className="text-[11px] text-[var(--color-error)] tracking-wider uppercase mb-0.5">last error</p>
                        <p className="text-[12px] text-[var(--color-text-dim)] truncate">{health.last_error}</p>
                      </div>
                    )}

                    {testResult && (
                      <div className={`p-2.5 border ${testResult.status === "ok" ? "border-[var(--color-success)]/20 bg-[var(--color-success)]/5" : "border-[var(--color-error)]/20 bg-[var(--color-error)]/5"} animate-fade-in`}>
                        <p className={`text-[12px] tracking-wider ${testResult.status === "ok" ? "text-[var(--color-success)]" : "text-[var(--color-error)]"}`}>
                          {testResult.message}
                        </p>
                      </div>
                    )}

                    {health.last_check && (
                      <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider flex items-center gap-1">
                        last check: <TimeAgo timestamp={health.last_check} live className="text-[11px]" />
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Schema Cache */}
      {schemaCache && (
        <div className="mt-8">
          <div className="section-header mb-4">
            <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">schema cache</span>
          </div>
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5">
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: "connections", value: schemaCache.cached_connections },
                { label: "entries", value: schemaCache.total_entries },
                { label: "ttl", value: `${schemaCache.ttl_seconds}s` },
              ].map((s) => (
                <div key={s.label}>
                  <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">{s.label}</p>
                  <p className="text-xs font-light tabular-nums">{s.value}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
