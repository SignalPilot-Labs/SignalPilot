"use client";

import { useEffect, useState } from "react";
import {
  Terminal,
  Database,
  Cpu,
  Server,
  Shield,
  DollarSign,
  Clock,
  Zap,
  BarChart3,
  ArrowRight,
  Loader2,
} from "lucide-react";
import { subscribeMetrics, getAudit, getBudgets, getConnections, getCacheStats, getConnectionsHealth } from "@/lib/api";
import type { MetricsSnapshot, AuditEntry, ConnectionInfo, ConnectionHealthStats } from "@/lib/types";
import { GovernancePipeline } from "@/components/ui/governance-pipeline";
import { EmptyTerminal, EmptyState } from "@/components/ui/empty-states";
import { RingGauge, Sparkline, StatusDot, MiniBar, StackedBar, ResponsiveAreaChart } from "@/components/ui/data-viz";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { SystemDiagram } from "@/components/ui/system-diagram";
import { SqlHighlight } from "@/components/ui/sql-highlight";
import { TimeAgo } from "@/components/ui/time-ago";

/* ── Metric card ── */
function MetricCard({
  label,
  value,
  subtext,
  icon: Icon,
  accentColor,
  sparkValues,
}: {
  label: string;
  value: string | number;
  subtext?: string;
  icon: React.ElementType;
  accentColor?: string;
  sparkValues?: number[];
}) {
  return (
    <div className="bg-[var(--color-bg-card)] p-5 hover:bg-[var(--color-bg-hover)] transition-all card-glow card-accent-top group relative overflow-hidden">
      <div className="flex items-center gap-2 mb-3">
        <Icon className={`w-3.5 h-3.5 ${accentColor || "text-[var(--color-text-dim)]"} transition-transform group-hover:scale-110`} strokeWidth={1.5} />
        <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">{label}</span>
      </div>
      <p className="text-xl font-light metric-value text-[var(--color-text)] animate-count-up">{value}</p>
      {subtext && (
        <p className="text-[10px] text-[var(--color-text-dim)] mt-1.5 tracking-wider">{subtext}</p>
      )}
      {/* Background sparkline on hover */}
      {sparkValues && sparkValues.length >= 3 && (
        <div className="absolute bottom-0 right-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none">
          <Sparkline values={sparkValues} width={80} height={24} color={accentColor?.includes("success") ? "var(--color-success)" : accentColor?.includes("error") ? "var(--color-error)" : "var(--color-text-dim)"} fillOpacity={0.08} />
        </div>
      )}
    </div>
  );
}

/* ── Status badge ── */
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

/* ── Helpers ── */

const eventTypeConfig: Record<string, { label: string; color: string }> = {
  query: { label: "QRY", color: "text-[var(--color-success)]" },
  execute: { label: "EXE", color: "text-blue-400" },
  connect: { label: "CON", color: "text-[var(--color-text-dim)]" },
  block: { label: "BLK", color: "text-[var(--color-error)]" },
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

  const latencyValues = recentAudit
    .filter(e => e.duration_ms != null)
    .slice(0, 20)
    .map(e => e.duration_ms || 0)
    .reverse();

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader
        title="dashboard"
        subtitle="live overview"
        description="signalpilot gateway status and metrics"
      />

      {/* ── System status bar ── */}
      <TerminalBar
        path="dashboard --watch"
        status={
          <StatusDot
            status={metrics?.sandbox_health === "healthy" && metrics?.kvm_available ? "healthy" : metrics ? "error" : "unknown"}
            size={4}
            pulse={metrics?.sandbox_health === "healthy"}
          />
        }
      >
        <div className="flex items-center gap-8 text-xs">
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
          {latencyValues.length > 3 && (
            <div className="flex items-center gap-2 ml-auto">
              <span className="text-[10px] text-[var(--color-text-dim)] tracking-wider">latency:</span>
              <Sparkline values={latencyValues} color="var(--color-success)" width={60} height={16} />
            </div>
          )}
          <div className={`${latencyValues.length <= 3 ? "ml-auto" : ""} flex items-center gap-2`}>
            <Shield className="w-3 h-3 text-[var(--color-success)]" strokeWidth={1.5} />
            <span className="text-[10px] text-[var(--color-text-dim)] tracking-wider">
              governance: active
            </span>
          </div>
        </div>
      </TerminalBar>

      {/* ── Metric cards — top row ── */}
      <div className="grid grid-cols-4 gap-px mb-px bg-[var(--color-border)] border border-[var(--color-border)] stagger-fade-in">
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
          accentColor="text-[var(--color-warning)]"
        />
      </div>

      {/* ── Stats cards — second row ── */}
      <div className="grid grid-cols-4 gap-px mb-8 bg-[var(--color-border)] stagger-fade-in">
        <MetricCard
          label="queries"
          value={auditStats.queries}
          icon={BarChart3}
          accentColor="text-[var(--color-success)]"
        />
        <MetricCard
          label="executions"
          value={auditStats.executions}
          icon={Zap}
          accentColor="text-blue-400"
        />
        <MetricCard
          label="blocked"
          value={auditStats.blocks}
          icon={Shield}
          accentColor={auditStats.blocks > 0 ? "text-[var(--color-error)]" : undefined}
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

      {/* ── Latency + Distribution row ── */}
      {latencyValues.length > 3 && (
        <div className="grid grid-cols-3 gap-4 mb-8 stagger-fade-in">
          <div className="col-span-2 border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4 card-accent-top">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Clock className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
                <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">query latency</span>
              </div>
              <span className="text-[10px] tabular-nums text-[var(--color-text-dim)]">last {latencyValues.length} ops</span>
            </div>
            <ResponsiveAreaChart values={latencyValues} height={80} color="var(--color-success)" />
          </div>
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4 card-accent-top">
            <div className="flex items-center gap-2 mb-3">
              <BarChart3 className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
              <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">operation mix</span>
            </div>
            <div className="space-y-3">
              <StackedBar
                segments={[
                  { value: auditStats.queries, color: "var(--color-success)", label: "queries" },
                  { value: auditStats.executions, color: "#60a5fa", label: "executions" },
                  { value: auditStats.blocks, color: "var(--color-error)", label: "blocked" },
                ]}
                width={200}
                height={8}
              />
              <div className="flex items-center gap-4 text-[9px] text-[var(--color-text-dim)] tracking-wider">
                <span className="flex items-center gap-1"><span className="w-2 h-2 bg-[var(--color-success)]" />queries</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 bg-blue-400" />exec</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 bg-[var(--color-error)]" />blocked</span>
              </div>
              <div className="pt-2 border-t border-[var(--color-border)] space-y-1.5">
                {[
                  { label: "queries", value: auditStats.queries, total: auditStats.total, color: "text-[var(--color-success)]" },
                  { label: "executions", value: auditStats.executions, total: auditStats.total, color: "text-blue-400" },
                  { label: "blocked", value: auditStats.blocks, total: auditStats.total, color: "text-[var(--color-error)]" },
                ].map(row => (
                  <div key={row.label} className="flex items-center justify-between">
                    <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">{row.label}</span>
                    <span className={`text-[10px] tabular-nums ${row.color}`}>
                      {row.value} <span className="text-[var(--color-text-dim)]">/ {row.total > 0 ? ((row.value / row.total) * 100).toFixed(0) : 0}%</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Governance Pipeline ── */}
      <div className="mb-8">
        <GovernancePipeline />
      </div>

      {/* ── System topology ── */}
      <div className="mb-8">
        <SystemDiagram
          connections={connections.length}
          activeSandboxes={metrics?.active_sandboxes ?? 0}
          governanceActive={true}
        />
      </div>

      {/* ── Two-column layout ── */}
      <div className="grid grid-cols-3 gap-4">
        {/* Recent activity — takes 2 cols */}
        <div className="col-span-2 border border-[var(--color-border)] bg-[var(--color-bg-card)] card-radial-glow">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
            <div className="flex items-center gap-2">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M2 6h2l1.5-3 1.5 6 1.5-3H11" stroke="var(--color-text-dim)" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                recent activity
              </span>
            </div>
            <a href="/audit" className="flex items-center gap-1 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider">
              view all <ArrowRight className="w-3 h-3" />
            </a>
          </div>
          <div className="divide-y divide-[var(--color-border)]">
            {recentAudit.length === 0 ? (
              <EmptyState
                icon={EmptyTerminal}
                title="no activity yet"
                description="connect a database and run queries to see the activity feed"
              />
            ) : (
              recentAudit.slice(0, 12).map((entry) => {
                const cfg = eventTypeConfig[entry.event_type] || eventTypeConfig.query;
                return (
                  <div
                    key={entry.id}
                    className="group/row hover:bg-[var(--color-bg-hover)] transition-all"
                  >
                    <div className="flex items-center gap-3 px-4 py-2.5">
                      <span className={`text-[9px] font-medium uppercase tracking-[0.15em] w-8 ${
                        entry.blocked ? "text-[var(--color-error)]" : cfg.color
                      }`}>
                        {cfg.label}
                      </span>
                      <span className="flex-1 text-xs truncate overflow-hidden">
                        {entry.sql
                          ? <SqlHighlight sql={entry.sql.slice(0, 80)} className="text-xs" />
                          : <span className="text-[var(--color-text-muted)]">{entry.metadata?.code_preview
                            ? String(entry.metadata.code_preview).slice(0, 80)
                            : entry.connection_name || "—"}</span>}
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
                      <TimeAgo
                        timestamp={entry.timestamp}
                        live
                        className="text-[10px] text-[var(--color-text-dim)] w-10 text-right flex-shrink-0"
                      />
                    </div>
                    {/* Hover-reveal detail row */}
                    <div className="grid grid-cols-[2rem_1fr] gap-3 px-4 max-h-0 overflow-hidden opacity-0 group-hover/row:max-h-16 group-hover/row:opacity-100 group-hover/row:pb-2.5 transition-all duration-200 ease-out">
                      <span />
                      <div className="flex items-center gap-4 text-[9px] text-[var(--color-text-dim)] tracking-wider">
                        {entry.connection_name && (
                          <span className="flex items-center gap-1">
                            <span className="w-1 h-1 bg-[var(--color-text-dim)] opacity-40" />
                            {entry.connection_name}
                          </span>
                        )}
                        {entry.sandbox_id && (
                          <span className="flex items-center gap-1 font-mono tabular-nums">
                            sbx:{entry.sandbox_id.slice(0, 8)}
                          </span>
                        )}
                        {entry.metadata?.governance_latency_ms != null && (
                          <span>gov: {Number(entry.metadata.governance_latency_ms).toFixed(1)}ms</span>
                        )}
                        {entry.metadata?.stages_applied != null && (
                          <span className="flex items-center gap-1">
                            stages: {String(entry.metadata.stages_applied)}
                          </span>
                        )}
                        {entry.blocked && entry.block_reason && (
                          <span className="text-[var(--color-error)]">
                            reason: {entry.block_reason}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right column — Connections + Cache */}
        <div className="space-y-4">
          {/* Connections overview */}
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] card-radial-glow">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
              <div className="flex items-center gap-2">
                <Database className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
                <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                  connections
                </span>
              </div>
              <a href="/connections" className="flex items-center gap-1 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider">
                manage <ArrowRight className="w-3 h-3" />
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
                      className="flex items-center gap-3 px-4 py-2.5 hover:bg-[var(--color-bg-hover)] transition-colors group"
                    >
                      <StatusDot
                        status={
                          health?.status === "healthy" ? "healthy" :
                          health?.status === "warning" ? "warning" :
                          health?.status === "degraded" || health?.status === "unhealthy" ? "error" :
                          "unknown"
                        }
                        size={4}
                        pulse={health?.status === "healthy"}
                      />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs text-[var(--color-text-muted)] truncate">{conn.name}</p>
                        <p className="text-[10px] text-[var(--color-text-dim)] truncate">
                          {conn.host}:{conn.port}/{conn.database}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        {health?.latency_p50_ms != null && (
                          <div className="flex items-center gap-1.5">
                            <MiniBar
                              value={health.latency_p50_ms}
                              max={200}
                              width={24}
                              height={3}
                              color={health.latency_p50_ms < 50 ? "var(--color-success)" : health.latency_p50_ms < 150 ? "var(--color-warning)" : "var(--color-error)"}
                            />
                            <span className="text-[10px] tabular-nums text-[var(--color-text-dim)]">
                              {health.latency_p50_ms.toFixed(0)}ms
                            </span>
                          </div>
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
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] card-radial-glow">
            <div className="px-4 py-3 border-b border-[var(--color-border)]">
              <div className="flex items-center gap-2">
                <Zap className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
                <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                  query cache
                </span>
              </div>
            </div>
            <div className="p-4 space-y-3">
              {cacheStats ? (
                <>
                  <div className="flex items-center gap-3">
                    <RingGauge
                      value={cacheStats.hit_rate * 100}
                      max={100}
                      size={36}
                      strokeWidth={3}
                      color={cacheStats.hit_rate > 0.7 ? "var(--color-success)" : cacheStats.hit_rate > 0.3 ? "var(--color-warning)" : "var(--color-error)"}
                    />
                    <div>
                      <p className={`text-lg font-light tabular-nums ${
                        cacheStats.hit_rate > 0.7 ? "text-[var(--color-success)]" :
                        cacheStats.hit_rate > 0.3 ? "text-[var(--color-warning)]" : "text-[var(--color-text)]"
                      }`}>
                        {(cacheStats.hit_rate * 100).toFixed(1)}%
                      </p>
                      <p className="text-[9px] text-[var(--color-text-dim)] tracking-wider">hit rate</p>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-3 pt-1">
                    <div>
                      <p className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">hits</p>
                      <p className="text-xs font-light tabular-nums text-[var(--color-success)]">{cacheStats.hits}</p>
                    </div>
                    <div>
                      <p className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">miss</p>
                      <p className="text-xs font-light tabular-nums text-[var(--color-text-muted)]">{cacheStats.misses}</p>
                    </div>
                    <div>
                      <p className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">size</p>
                      <p className="text-xs font-light tabular-nums">{cacheStats.entries}/{cacheStats.max_entries}</p>
                    </div>
                  </div>
                </>
              ) : (
                <div className="flex items-center gap-2">
                  <div className="w-full h-1 animate-shimmer" />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
