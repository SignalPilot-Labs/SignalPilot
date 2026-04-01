"use client";

import { useEffect, useState, useCallback } from "react";
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
  getConnectionsHealth,
  getConnectionHealth,
  testConnection,
  getConnections,
  getCacheStats,
  getSchemaCache,
} from "@/lib/api";
import type { ConnectionHealthStats, ConnectionInfo } from "@/lib/types";
import { EmptyChart, EmptyState } from "@/components/ui/empty-states";

const statusConfig: Record<string, { color: string; bg: string; icon: React.ElementType; label: string }> = {
  healthy: { color: "text-[var(--color-success)]", bg: "bg-[var(--color-success)]", icon: CheckCircle2, label: "healthy" },
  warning: { color: "text-[var(--color-warning)]", bg: "bg-[var(--color-warning)]", icon: AlertTriangle, label: "warning" },
  degraded: { color: "text-orange-400", bg: "bg-orange-400", icon: AlertTriangle, label: "degraded" },
  unhealthy: { color: "text-[var(--color-error)]", bg: "bg-[var(--color-error)]", icon: XCircle, label: "unhealthy" },
  unknown: { color: "text-[var(--color-text-dim)]", bg: "bg-[var(--color-text-dim)]", icon: Activity, label: "unknown" },
};

/* ── Latency bar with SVG visualization ── */
function LatencyBar({ label, value, maxMs = 500 }: { label: string; value: number | null; maxMs?: number }) {
  if (value === null) return null;
  const pct = Math.min(100, (value / maxMs) * 100);
  const color = value < 50 ? "var(--color-success)" : value < 200 ? "var(--color-warning)" : "var(--color-error)";

  return (
    <div className="flex items-center gap-3">
      <span className="text-[9px] text-[var(--color-text-dim)] w-8 text-right uppercase tracking-[0.15em]">{label}</span>
      <div className="flex-1 h-1.5 bg-[var(--color-bg)] overflow-hidden relative">
        <div className="h-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-[10px] tabular-nums text-[var(--color-text-dim)] w-16 text-right tracking-wider">{value.toFixed(1)}ms</span>
    </div>
  );
}

export default function HealthPage() {
  const [healthData, setHealthData] = useState<ConnectionHealthStats[]>([]);
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { status: string; message: string }>>({});
  const [cacheStats, setCacheStats] = useState<{ entries: number; max_entries: number; hits: number; misses: number; hit_rate: number } | null>(null);
  const [schemaCache, setSchemaCache] = useState<{ cached_connections: number; total_entries: number; ttl_seconds: number } | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [health, conns, cache, schema] = await Promise.all([
        getConnectionsHealth().catch(() => ({ connections: [] })),
        getConnections().catch(() => []),
        getCacheStats().catch(() => null),
        getSchemaCache().catch(() => null),
      ]);
      setHealthData(health.connections);
      setConnections(conns);
      setCacheStats(cache);
      setSchemaCache(schema);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    refresh();
    if (!autoRefresh) return;
    const i = setInterval(refresh, 10000);
    return () => clearInterval(i);
  }, [refresh, autoRefresh]);

  async function handleTest(name: string) {
    setTesting(name);
    try {
      const result = await testConnection(name);
      setTestResults((prev) => ({ ...prev, [name]: result }));
      try {
        const h = await getConnectionHealth(name);
        setHealthData((prev) => prev.map((item) => item.connection_name === name ? h : item));
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
      <div className="flex items-center justify-between mb-8">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-lg font-light tracking-wide">health</h1>
            <span className="text-[9px] text-[var(--color-text-dim)] tracking-[0.15em] uppercase">/ monitoring</span>
          </div>
          <p className="text-xs text-[var(--color-text-dim)] tracking-wider">
            connection health, latency, and cache performance
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-[10px] text-[var(--color-text-dim)] cursor-pointer tracking-wider px-2 py-1.5 border border-[var(--color-border)] hover:border-[var(--color-border-hover)] transition-colors">
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} className="rounded-none" />
            auto (10s)
          </label>
          <button onClick={refresh} disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} strokeWidth={1.5} />
            refresh
          </button>
        </div>
      </div>

      {/* Overview cards */}
      <div className="grid grid-cols-4 gap-px mb-8 bg-[var(--color-border)] stagger-fade-in">
        {[
          { label: "connections", value: `${overallHealthy}/${overallTotal}`, sub: "healthy", icon: Wifi, accent: overallHealthy === overallTotal && overallTotal > 0 ? "text-[var(--color-success)]" : undefined },
          { label: "avg latency", value: avgLatency != null ? `${avgLatency.toFixed(1)}ms` : "--", sub: "all connections", icon: Clock },
          { label: "query cache", value: cacheStats ? `${(cacheStats.hit_rate * 100).toFixed(1)}%` : "--", sub: cacheStats ? `${cacheStats.hits} hits / ${cacheStats.misses} misses` : "hit rate", icon: Zap, accent: cacheStats && cacheStats.hit_rate > 0.7 ? "text-[var(--color-success)]" : undefined },
          { label: "schema cache", value: schemaCache ? String(schemaCache.cached_connections) : "--", sub: schemaCache ? `${schemaCache.total_entries} entries, ttl ${schemaCache.ttl_seconds}s` : "cached connections", icon: Database },
        ].map((card) => (
          <div key={card.label} className="bg-[var(--color-bg-card)] p-5 hover:bg-[var(--color-bg-hover)] transition-colors card-accent-top">
            <div className="flex items-center gap-2 mb-3">
              <card.icon className={`w-3.5 h-3.5 ${card.accent || "text-[var(--color-text-dim)]"}`} strokeWidth={1.5} />
              <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">{card.label}</span>
            </div>
            <p className={`text-xl font-light tabular-nums ${card.accent || ""}`}>{card.value}</p>
            <p className="text-[10px] text-[var(--color-text-dim)] mt-1 tracking-wider">{card.sub}</p>
          </div>
        ))}
      </div>

      {/* Connection health cards */}
      {loading && healthData.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24">
          <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)] mb-3" />
          <p className="text-xs text-[var(--color-text-dim)] tracking-wider">loading health data...</p>
        </div>
      ) : healthData.length === 0 ? (
        <EmptyState
          icon={EmptyChart}
          title="no health data"
          description="connect a database and run queries to see health metrics"
        />
      ) : (
        <div className="space-y-4">
          <div className="section-header">
            <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">connection health</span>
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
                      <span className={`w-2 h-2 ${cfg.bg}`} />
                      <div>
                        <h3 className="text-xs text-[var(--color-text)]">{health.connection_name}</h3>
                        <span className="text-[10px] text-[var(--color-text-dim)] tracking-wider">
                          {health.db_type}{conn ? ` — ${conn.host}:${conn.port}` : ""}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`flex items-center gap-1 text-[10px] tracking-wider ${cfg.color}`}>
                        <StatusIcon className="w-3 h-3" strokeWidth={1.5} /> {cfg.label}
                      </span>
                      <button onClick={() => handleTest(health.connection_name)} disabled={testing === health.connection_name}
                        className="flex items-center gap-1 px-2 py-1 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-all disabled:opacity-50 tracking-wider">
                        {testing === health.connection_name ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <Activity className="w-2.5 h-2.5" strokeWidth={1.5} />}
                        test
                      </button>
                    </div>
                  </div>

                  <div className="px-5 py-4 space-y-4">
                    {/* Latency bars */}
                    <div className="space-y-2">
                      <div className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">latency</div>
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
                          <p className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">{stat.label}</p>
                          <p className={`text-xs font-light tabular-nums ${stat.color}`}>{stat.value}</p>
                        </div>
                      ))}
                      {health.error_rate != null && (
                        <div>
                          <p className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">error rate</p>
                          <p className={`text-xs font-light tabular-nums ${
                            health.error_rate > 0.1 ? "text-[var(--color-error)]" : health.error_rate > 0 ? "text-[var(--color-warning)]" : "text-[var(--color-success)]"
                          }`}>{(health.error_rate * 100).toFixed(1)}%</p>
                        </div>
                      )}
                      {health.consecutive_failures != null && health.consecutive_failures > 0 && (
                        <div>
                          <p className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">consec fails</p>
                          <p className="text-xs font-light tabular-nums text-[var(--color-error)]">{health.consecutive_failures}</p>
                        </div>
                      )}
                    </div>

                    {health.last_error && (
                      <div className="p-2.5 border border-[var(--color-error)]/20 bg-[var(--color-error)]/5">
                        <p className="text-[9px] text-[var(--color-error)] tracking-wider uppercase mb-0.5">last error</p>
                        <p className="text-[10px] text-[var(--color-text-dim)] truncate">{health.last_error}</p>
                      </div>
                    )}

                    {testResult && (
                      <div className={`p-2.5 border ${testResult.status === "ok" ? "border-[var(--color-success)]/20 bg-[var(--color-success)]/5" : "border-[var(--color-error)]/20 bg-[var(--color-error)]/5"} animate-fade-in`}>
                        <p className={`text-[10px] tracking-wider ${testResult.status === "ok" ? "text-[var(--color-success)]" : "text-[var(--color-error)]"}`}>
                          {testResult.message}
                        </p>
                      </div>
                    )}

                    {health.last_check && (
                      <p className="text-[9px] text-[var(--color-text-dim)] tracking-wider">
                        last check: {new Date(health.last_check * 1000).toLocaleString()}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Cache Details */}
      {cacheStats && (
        <div className="mt-8">
          <div className="section-header mb-4">
            <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">cache performance</span>
          </div>
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5">
            <div className="grid grid-cols-2 gap-8">
              <div>
                <div className="text-[10px] text-[var(--color-text-dim)] mb-3 flex items-center gap-2 tracking-wider">
                  <BarChart3 className="w-3 h-3" strokeWidth={1.5} /> query cache
                </div>
                <div className="space-y-3">
                  <div>
                    <div className="flex justify-between text-[10px] mb-1">
                      <span className="text-[var(--color-text-dim)] tracking-wider">hit rate</span>
                      <span className="tabular-nums">{(cacheStats.hit_rate * 100).toFixed(1)}%</span>
                    </div>
                    <div className="w-full h-1.5 bg-[var(--color-bg)] overflow-hidden">
                      <div className="h-full bg-[var(--color-success)] transition-all" style={{ width: `${cacheStats.hit_rate * 100}%` }} />
                    </div>
                  </div>
                  <div>
                    <div className="flex justify-between text-[10px] mb-1">
                      <span className="text-[var(--color-text-dim)] tracking-wider">capacity</span>
                      <span className="tabular-nums">{cacheStats.entries} / {cacheStats.max_entries}</span>
                    </div>
                    <div className="w-full h-1.5 bg-[var(--color-bg)] overflow-hidden">
                      <div className="h-full bg-[var(--color-text-dim)] transition-all" style={{ width: `${(cacheStats.entries / cacheStats.max_entries) * 100}%` }} />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3 pt-1">
                    <div>
                      <p className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">hits</p>
                      <p className="text-xs font-light tabular-nums text-[var(--color-success)]">{cacheStats.hits.toLocaleString()}</p>
                    </div>
                    <div>
                      <p className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">misses</p>
                      <p className="text-xs font-light tabular-nums text-[var(--color-text-muted)]">{cacheStats.misses.toLocaleString()}</p>
                    </div>
                  </div>
                </div>
              </div>
              {schemaCache && (
                <div>
                  <div className="text-[10px] text-[var(--color-text-dim)] mb-3 flex items-center gap-2 tracking-wider">
                    <TrendingUp className="w-3 h-3" strokeWidth={1.5} /> schema cache
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    {[
                      { label: "connections", value: schemaCache.cached_connections },
                      { label: "entries", value: schemaCache.total_entries },
                      { label: "ttl", value: `${schemaCache.ttl_seconds}s` },
                    ].map((s) => (
                      <div key={s.label}>
                        <p className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">{s.label}</p>
                        <p className="text-xs font-light tabular-nums">{s.value}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
