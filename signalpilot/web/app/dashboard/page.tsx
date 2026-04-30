"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
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
  CreditCard,
  Key,
  Plug,
  Plus,
} from "lucide-react";
import { subscribeMetrics } from "@/lib/api";
import { useConnectionsHealth, useCacheStats, useBudgets, useAudit, usePlan, prefetchCommonData } from "@/lib/hooks/use-gateway-data";
import type { MetricsSnapshot, AuditEntry, ConnectionHealthStats } from "@/lib/types";
import { useConnection } from "@/lib/connection-context";
import { useAppAuth } from "@/lib/auth-context";
import { useSubscription } from "@/lib/subscription-context";
import { useBackendClient } from "@/lib/backend-client";
import type { UsageSummaryResponse, DailyUsagePoint } from "@/lib/backend-client";
import { GovernancePipeline } from "@/components/ui/governance-pipeline";
import { EmptyTerminal, EmptyState } from "@/components/ui/empty-states";
import { RingGauge, Sparkline, StatusDot, MiniBar, StackedBar, ResponsiveAreaChart } from "@/components/ui/data-viz";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { SystemDiagram } from "@/components/ui/system-diagram";
import { SqlHighlight } from "@/components/ui/sql-highlight";
import { TimeAgo } from "@/components/ui/time-ago";
import { DashboardSkeleton } from "@/components/ui/skeleton";
import { useOnboardingStatus } from "@/lib/onboarding";
import { useTierBranding } from "@/lib/hooks/use-tier-branding";
import { TierWordmark } from "@/components/branding/tier-wordmark";
import { TierBadge } from "@/components/branding/tier-badge";

/* ── Metric card ── */
function MetricCard({
  label,
  value,
  subtext,
  icon: Icon,
  accentColor,
  sparkValues,
  actionHref,
  actionLabel,
}: {
  label: string;
  value: string | number;
  subtext?: string;
  icon: React.ElementType;
  accentColor?: string;
  sparkValues?: number[];
  actionHref?: string;
  actionLabel?: string;
}) {
  return (
    <div className="bg-[var(--color-bg-card)] p-5 hover:bg-[var(--color-bg-hover)] transition-all card-glow card-accent-top group relative overflow-hidden">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon className={`w-4 h-4 ${accentColor || "text-[var(--color-text-dim)]"} transition-transform group-hover:scale-110`} strokeWidth={1.5} />
          <span className="text-[12px] text-[var(--color-text-muted)] uppercase tracking-[0.15em]">{label}</span>
        </div>
        {actionHref && (
          <Link href={actionHref} className="flex items-center gap-1 px-1.5 py-0.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider">
            <Plus className="w-2.5 h-2.5" />{actionLabel || "add"}
          </Link>
        )}
      </div>
      <p className="text-2xl font-light metric-value text-[var(--color-text)] animate-count-up">{value}</p>
      {subtext && (
        <p className="text-[12px] text-[var(--color-text-muted)] mt-1.5 tracking-wider">{subtext}</p>
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
    <span className="flex items-center gap-1.5 text-[12px] text-[var(--color-success)] tracking-wider">
      <span className="w-1.5 h-1.5 bg-[var(--color-success)] pulse-dot" />
      healthy
    </span>
  ) : (
    <span className="flex items-center gap-1.5 text-[12px] text-[var(--color-error)] tracking-wider">
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

/* ── Cloud status section ── */

/** Inner content for the subscription/keys/MCP grid.
 *  Receives keyCount as a prop — no internal fetch needed. */
function CloudStatusContent({ keyCount }: { keyCount: number | null }) {
  const { status } = useSubscription();
  const { data: plan } = usePlan();
  const planTier = plan?.tier ?? "free";
  const maxApiKeys = plan?.limits.api_keys === "unlimited" ? "∞" : (plan?.limits.api_keys ?? 1);

  const statusLabel = status === "past_due" ? "past due" : status;

  // MCP endpoint detection — static check, no API call
  const mcpUrl =
    process.env.NEXT_PUBLIC_MCP_URL ||
    process.env.NEXT_PUBLIC_GATEWAY_URL ||
    null;
  const mcpConfigured = Boolean(mcpUrl);
  const mcpDisplay = mcpUrl
    ? mcpUrl.replace(/^https?:\/\//, "").replace(/\/$/, "")
    : null;

  const showUpgrade = planTier === "free" || planTier === "pro";

  return (
    <div className="grid grid-cols-3 gap-px mb-4 bg-[var(--color-border)] border border-[var(--color-border)]">
      {/* Card 1: Subscription */}
      <div className="bg-[var(--color-bg-card)] p-5 hover:bg-[var(--color-bg-hover)] transition-all card-glow card-accent-top">
        <div className="flex items-center gap-2 mb-3">
          <CreditCard className="w-4 h-4 text-[var(--color-text-dim)]" strokeWidth={1.5} />
          <span className="text-[12px] leading-none text-[var(--color-text-muted)] uppercase tracking-[0.15em]">
            subscription
          </span>
        </div>
        <div className="mb-1.5">
          {planTier === "free" ? (
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-[5px] h-[5px] flex-shrink-0 bg-[var(--color-text-dim)]" aria-hidden="true" />
              <span className="text-[11px] leading-none tracking-[0.15em] uppercase text-[var(--color-text-dim)]">free</span>
            </span>
          ) : (
            <TierBadge />
          )}
        </div>
        <p className="text-[12px] text-[var(--color-text-muted)] mt-1.5 tracking-wider">
          {statusLabel}
        </p>
        {showUpgrade && (
          <Link
            href="/settings/billing"
            className="inline-flex items-center gap-1 mt-2 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
          >
            upgrade <ArrowRight className="w-3 h-3" />
          </Link>
        )}
      </div>

      {/* Card 2: API Keys */}
      <div className="bg-[var(--color-bg-card)] p-5 hover:bg-[var(--color-bg-hover)] transition-all card-glow card-accent-top">
        <div className="flex items-center gap-2 mb-3">
          <Key className="w-4 h-4 text-[var(--color-text-dim)]" strokeWidth={1.5} />
          <span className="text-[12px] text-[var(--color-text-muted)] uppercase tracking-[0.15em]">
            api keys
          </span>
        </div>
        <p className="text-2xl font-light metric-value text-[var(--color-text)]">
          {keyCount === null ? (
            <Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-dim)] inline-block" />
          ) : keyCount === -1 ? (
            "—"
          ) : (
            keyCount
          )}
        </p>
        <p className="text-[12px] text-[var(--color-text-muted)] mt-1.5 tracking-wider">
          of {maxApiKeys} allowed
        </p>
        <Link
          href="/settings/api-keys"
          className="inline-flex items-center gap-1 mt-2 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
        >
          manage <ArrowRight className="w-3 h-3" />
        </Link>
      </div>

      {/* Card 3: MCP Endpoint */}
      <div className="bg-[var(--color-bg-card)] p-5 hover:bg-[var(--color-bg-hover)] transition-all card-glow card-accent-top">
        <div className="flex items-center gap-2 mb-3">
          <Plug className="w-4 h-4 text-[var(--color-text-dim)]" strokeWidth={1.5} />
          <span className="text-[12px] text-[var(--color-text-muted)] uppercase tracking-[0.15em]">
            mcp endpoint
          </span>
        </div>
        <div className="flex items-center gap-2 mb-1.5">
          <StatusDot
            status={mcpConfigured ? "healthy" : "error"}
            size={4}
            pulse={mcpConfigured}
          />
          <span className={`text-[12px] tracking-wider ${mcpConfigured ? "text-[var(--color-success)]" : "text-[var(--color-text-dim)]"}`}>
            {mcpConfigured ? "configured" : "not configured"}
          </span>
        </div>
        {mcpDisplay && (
          <p className="text-[12px] text-[var(--color-text-muted)] mt-1.5 tracking-wider font-mono truncate">
            {mcpDisplay}
          </p>
        )}
        <Link
          href="/settings/mcp-connect"
          className="inline-flex items-center gap-1 mt-2 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
        >
          connect <ArrowRight className="w-3 h-3" />
        </Link>
      </div>
    </div>
  );
}

/** Usage analytics card — receives summary and sparkPoints as props, no fetch of its own. */
function UsageAnalyticsContent({
  summary,
  sparkPoints,
}: {
  summary: UsageSummaryResponse | null;
  sparkPoints: DailyUsagePoint[] | null;
}) {
  const sparkValues = sparkPoints ? sparkPoints.map((d) => d.requests) : [];
  const last7DaysTotal = summary?.total_requests_7d ?? null;
  const activeKeys = summary?.active_keys ?? null;
  const latestActivity = summary?.last_activity_at ?? null;

  return (
    <div className="mb-4">
      <div className="grid grid-cols-3 gap-px bg-[var(--color-border)] border border-[var(--color-border)]">
        {/* Card 1: Total requests (7d) */}
        <div className="bg-[var(--color-bg-card)] p-5 hover:bg-[var(--color-bg-hover)] transition-all card-glow card-accent-top">
          <div className="flex items-center gap-2 mb-3">
            <BarChart3 className="w-4 h-4 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[12px] text-[var(--color-text-muted)] uppercase tracking-[0.15em]">
              requests (7d)
            </span>
          </div>
          <p className="text-2xl font-light metric-value text-[var(--color-text)] tabular-nums">
            {last7DaysTotal === null ? (
              <Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-dim)] inline-block" />
            ) : last7DaysTotal.toLocaleString()}
          </p>
          {sparkValues.length >= 2 && (
            <div className="mt-2">
              <Sparkline
                values={sparkValues}
                width={80}
                height={20}
                color="var(--color-success)"
                fillOpacity={0.1}
              />
            </div>
          )}
        </div>

        {/* Card 2: Active keys */}
        <div className="bg-[var(--color-bg-card)] p-5 hover:bg-[var(--color-bg-hover)] transition-all card-glow card-accent-top">
          <div className="flex items-center gap-2 mb-3">
            <Key className="w-4 h-4 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[12px] text-[var(--color-text-muted)] uppercase tracking-[0.15em]">
              active keys
            </span>
          </div>
          <p className="text-2xl font-light metric-value text-[var(--color-text)] tabular-nums">
            {activeKeys === null ? (
              <Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-dim)] inline-block" />
            ) : activeKeys}
          </p>
          <p className="text-[12px] text-[var(--color-text-muted)] mt-1.5 tracking-wider">
            {summary !== null ? `of ${summary.active_keys} active (7d)` : ""}
          </p>
        </div>

        {/* Card 3: Last activity */}
        <div className="bg-[var(--color-bg-card)] p-5 hover:bg-[var(--color-bg-hover)] transition-all card-glow card-accent-top">
          <div className="flex items-center gap-2 mb-3">
            <Clock className="w-4 h-4 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[12px] text-[var(--color-text-muted)] uppercase tracking-[0.15em]">
              last activity
            </span>
          </div>
          {summary === null ? (
            <Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-dim)]" />
          ) : latestActivity ? (
            <TimeAgo
              timestamp={new Date(latestActivity).getTime()}
              className="text-lg font-light text-[var(--color-text)] tracking-wider"
            />
          ) : (
            <p className="text-lg font-light text-[var(--color-text-dim)] tracking-wider">—</p>
          )}
        </div>
      </div>

      {/* View details link */}
      <div className="flex justify-end mt-2">
        <Link
          href="/settings/usage"
          aria-label="view full usage analytics"
          className="inline-flex items-center gap-1 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
        >
          view details <ArrowRight className="w-3 h-3" />
        </Link>
      </div>
    </div>
  );
}

/** Shared content component that fetches keys + usage summary in parallel and
 *  passes them to CloudStatusContent and UsageAnalyticsContent. */
function CloudAndUsageContent() {
  const client = useBackendClient();
  const [keyCount, setKeyCount] = useState<number | null>(null);
  const [summary, setSummary] = useState<UsageSummaryResponse | null>(null);
  const [sparkPoints, setSparkPoints] = useState<DailyUsagePoint[] | null>(null);

  useEffect(() => {
    let cancelled = false;

    // Fetch keys for key count and usage summary + daily sparkline in parallel
    Promise.all([
      client.getApiKeys(),
      client.getUsageSummary().catch(() => null),
      client.getUsageDaily(7).catch(() => null),
    ]).then(([keysData, summaryData, dailyRes]) => {
      if (cancelled) return;
      setKeyCount(keysData.length);

      if (summaryData !== null) {
        setSummary(summaryData);
      } else {
        // Fall back to mock summary derived from keys
        import("@/lib/mock-usage").then(({ generateDailyUsage, generateKeyUsage, getRateLimitStatus }) => {
          if (cancelled) return;
          const mockKeyStats = keysData.map((k) => generateKeyUsage(k));
          const mockRateLimit = getRateLimitStatus("free");
          const mockSummary: UsageSummaryResponse = {
            total_requests: mockKeyStats.reduce((sum, s) => sum + s.totalRequests, 0),
            total_requests_today: mockRateLimit.used,
            total_requests_7d: mockKeyStats.reduce((sum, s) => sum + s.last7Days, 0),
            total_requests_30d: mockKeyStats.reduce((sum, s) => sum + s.totalRequests, 0),
            daily_limit: mockRateLimit.limit,
            daily_used: mockRateLimit.used,
            daily_reset_at: mockRateLimit.resetAt,
            active_keys: mockKeyStats.filter((s) => s.last7Days > 0).length,
            last_activity_at: mockKeyStats.reduce<string | null>((latest, s) => {
              if (!latest) return s.lastUsedAt;
              return s.lastUsedAt > latest ? s.lastUsedAt : latest;
            }, null),
          };
          setSummary(mockSummary);
          const mockDaily = generateDailyUsage(keysData, 7);
          setSparkPoints(mockDaily);
        });
        return;
      }

      if (dailyRes !== null) {
        setSparkPoints(dailyRes.points);
      } else {
        import("@/lib/mock-usage").then(({ generateDailyUsage }) => {
          if (cancelled) return;
          setSparkPoints(generateDailyUsage(keysData, 7));
        });
      }
    }).catch(() => {
      if (!cancelled) {
        setKeyCount(-1);
        setSummary({
          total_requests: 0,
          total_requests_today: 0,
          total_requests_7d: 0,
          total_requests_30d: 0,
          daily_limit: 1000,
          daily_used: 0,
          daily_reset_at: new Date(Date.now() + 86400000).toISOString(),
          active_keys: 0,
          last_activity_at: null,
        });
        setSparkPoints([]);
      }
    });

    return () => { cancelled = true; };
  }, [client]);

  return (
    <>
      <CloudStatusContent keyCount={keyCount} />
      <UsageAnalyticsContent summary={summary} sparkPoints={sparkPoints} />
    </>
  );
}

/** Gate — calls useAppAuth() and conditionally renders CloudAndUsageContent.
 *  useBackendClient() is NEVER called here; it lives only in CloudAndUsageContent. */
function CloudStatusSection() {
  const { isCloudMode } = useAppAuth();
  if (!isCloudMode) return null;
  return <CloudAndUsageContent />;
}

/* ── Signed-in user greeting ── */
function UserGreeting() {
  const { isCloudMode, user } = useAppAuth();
  const b = useTierBranding();

  if (!isCloudMode || !user) return null;

  const email = user.email ?? "—";

  const showTierPrefix = b.enabled && b.tier !== "free";

  return (
    <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider mb-4">
      {showTierPrefix && (
        <>
          <TierWordmark variant="header" />
          <span className="mx-2 text-[var(--color-text-dim)]">·</span>
        </>
      )}
      signed in as{" "}
      <span className="text-[var(--color-text-muted)]">{email}</span>
    </p>
  );
}

/* ── DashboardOnboardingCheck — only rendered when isCloudMode is true ── */
function DashboardOnboardingCheck() {
  const router = useRouter();
  const { activeOrgId, isAuthenticated } = useAppAuth();
  const { isComplete, isLoading, markComplete } = useOnboardingStatus();
  const [autoCompleting, setAutoCompleting] = useState(false);

  useEffect(() => {
    if (isLoading) return;

    // Not signed in — nothing to do, auth protection handled by middleware
    if (!isAuthenticated) return;

    if (isComplete === true) return; // already done

    if (activeOrgId) {
      // User has an active org but onboarding flag not set.
      // Auto-mark complete — they don't need the wizard.
      setAutoCompleting(true);
      markComplete()
        .catch(() => {})
        .finally(() => setAutoCompleting(false));
    } else {
      // No org — send to onboarding to create/join a team
      router.push("/onboarding");
    }
  }, [isLoading, isComplete, activeOrgId, isAuthenticated, router, markComplete]);

  if (isLoading || autoCompleting || (isComplete === false && !activeOrgId)) {
    return <DashboardSkeleton />;
  }

  return <DashboardContent />;
}

/* ── DashboardGate — new default export ── */
export default function DashboardGate() {
  const { isCloudMode, isLoaded } = useAppAuth();

  if (!isLoaded) {
    return <DashboardSkeleton />;
  }

  if (isCloudMode) {
    return <DashboardOnboardingCheck />;
  }

  return <DashboardContent />;
}

function DashboardContent() {
  const { isCloudMode } = useAppAuth();
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const { connections } = useConnection();

  // SWR data hooks
  const { data: auditData } = useAudit({ limit: 50 });
  const { data: budgetData } = useBudgets();
  const { data: cacheStats } = useCacheStats();
  const { data: healthData } = useConnectionsHealth();

  // Derive audit entries + stats from SWR data
  const recentAudit: AuditEntry[] = auditData?.entries ?? [];
  const auditStats = useMemo(() => {
    const stats = { queries: 0, executions: 0, blocks: 0, total: recentAudit.length };
    for (const e of recentAudit) {
      if (e.event_type === "query") stats.queries++;
      else if (e.event_type === "execute") stats.executions++;
      if (e.blocked) stats.blocks++;
    }
    return stats;
  }, [recentAudit]);

  // Derive connection health map from SWR data
  const connHealth = useMemo(() => {
    const map: Record<string, ConnectionHealthStats> = {};
    if (healthData?.connections) {
      for (const h of healthData.connections) {
        map[h.connection_name] = h;
      }
    }
    return map;
  }, [healthData]);

  // Prefetch common data on mount for faster navigation to other pages
  useEffect(() => { prefetchCommonData(); }, []);

  // SSE metrics subscription — live stream, not a REST fetch
  useEffect(() => {
    const unsub = subscribeMetrics((data) => {
      setMetrics(data);
    });
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
            status={metrics?.sandbox_health === "healthy" && metrics?.sandbox_available ? "healthy" : metrics ? "error" : "unknown"}
            size={4}
            pulse={metrics?.sandbox_health === "healthy"}
          />
        }
      >
        <div className="flex items-center gap-8 text-xs">
          {!isCloudMode && (
            <div className="flex items-center gap-2">
              <Server className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
              <span className="text-[var(--color-text-dim)]">sandbox_mgr:</span>
              <code className="text-[12px] text-[var(--color-text)]">
                {metrics?.sandbox_manager || "—"}
              </code>
              <StatusBadge ok={metrics ? metrics.sandbox_health === "healthy" : null} />
            </div>
          )}
          {!isCloudMode && (
            <div className="flex items-center gap-2">
              <Cpu className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
              <span className="text-[var(--color-text-dim)]">sandbox:</span>
              <StatusBadge ok={metrics ? metrics.sandbox_available : null} />
            </div>
          )}
          {latencyValues.length > 3 && (
            <div className="flex items-center gap-2 ml-auto">
              <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider">latency:</span>
              <Sparkline values={latencyValues} color="var(--color-success)" width={60} height={16} />
            </div>
          )}
          <div className={`${latencyValues.length <= 3 ? "ml-auto" : ""} flex items-center gap-2`}>
            <Shield className="w-3 h-3 text-[var(--color-success)]" strokeWidth={1.5} />
            <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
              governance: active
            </span>
          </div>
        </div>
      </TerminalBar>

      {/* ── Metric cards — top row ── */}
      <div className={`grid ${isCloudMode ? "grid-cols-2" : "grid-cols-4"} gap-px mb-px bg-[var(--color-border)] border border-[var(--color-border)] stagger-fade-in`}>
        {!isCloudMode && (
          <MetricCard
            label="active sandboxes"
            value={metrics?.active_sandboxes ?? "—"}
            subtext={metrics ? `${metrics.running_sandboxes} running` : undefined}
            icon={Terminal}
          />
        )}
        {!isCloudMode && (
          <MetricCard
            label="sandbox instances"
            value={metrics ? `${metrics.active_sandbox_instances} / ${metrics.max_sandbox_instances}` : "—"}
            icon={Cpu}
          />
        )}
        <MetricCard
          label="connections"
          value={connections.length}
          subtext={connections.length > 0 ? connections.map(c => c.db_type).filter((v, i, a) => a.indexOf(v) === i).join(", ") : undefined}
          icon={Database}
          actionHref="/connections?action=new"
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
                <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">query latency</span>
              </div>
              <span className="text-[12px] tabular-nums text-[var(--color-text-dim)]">last {latencyValues.length} ops</span>
            </div>
            <ResponsiveAreaChart values={latencyValues} height={80} color="var(--color-success)" />
          </div>
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4 card-accent-top">
            <div className="flex items-center gap-2 mb-3">
              <BarChart3 className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
              <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">operation mix</span>
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
              <div className="flex items-center gap-4 text-[11px] text-[var(--color-text-dim)] tracking-wider">
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
                    <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider">{row.label}</span>
                    <span className={`text-[12px] tabular-nums ${row.color}`}>
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
          activeSandboxes={isCloudMode ? 0 : (metrics?.active_sandboxes ?? 0)}
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
              <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                recent activity
              </span>
            </div>
            <Link href="/audit" className="flex items-center gap-1 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider">
              view all <ArrowRight className="w-3 h-3" />
            </Link>
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
                      <span className={`text-[11px] font-medium uppercase tracking-[0.15em] w-8 ${
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
                        <span className="text-[11px] px-1.5 py-0.5 border border-[var(--color-error)]/30 text-[var(--color-error)] tracking-wider uppercase">
                          blocked
                        </span>
                      )}
                      {entry.rows_returned != null && (
                        <span className="text-[12px] tabular-nums text-[var(--color-text-dim)]">
                          {entry.rows_returned}r
                        </span>
                      )}
                      {entry.duration_ms != null && (
                        <span className="text-[12px] tabular-nums text-[var(--color-text-dim)]">
                          {entry.duration_ms.toFixed(0)}ms
                        </span>
                      )}
                      <TimeAgo
                        timestamp={entry.timestamp}
                        live
                        className="text-[12px] text-[var(--color-text-dim)] w-10 text-right flex-shrink-0"
                      />
                    </div>
                    {/* Hover-reveal detail row */}
                    <div className="grid grid-cols-[2rem_1fr] gap-3 px-4 max-h-0 overflow-hidden opacity-0 group-hover/row:max-h-16 group-hover/row:opacity-100 group-hover/row:pb-2.5 transition-all duration-200 ease-out">
                      <span />
                      <div className="flex items-center gap-4 text-[11px] text-[var(--color-text-dim)] tracking-wider">
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
                <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                  connections
                </span>
              </div>
              <div className="flex items-center gap-3">
                <Link href="/connections?action=new" className="flex items-center gap-1 px-2 py-0.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider">
                  <Plus className="w-3 h-3" /> add
                </Link>
                <Link href="/connections" className="flex items-center gap-1 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider">
                  manage <ArrowRight className="w-3 h-3" />
                </Link>
              </div>
            </div>
            <div className="divide-y divide-[var(--color-border)]">
              {connections.length === 0 ? (
                <div className="px-4 py-10 text-center">
                  <Database className="w-5 h-5 mx-auto mb-2 text-[var(--color-text-dim)] opacity-20" strokeWidth={1} />
                  <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
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
                        <p className="text-[12px] text-[var(--color-text-dim)] truncate">
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
                            <span className="text-[12px] tabular-nums text-[var(--color-text-dim)]">
                              {health.latency_p50_ms.toFixed(0)}ms
                            </span>
                          </div>
                        )}
                        <span className="text-[11px] px-1.5 py-0.5 border border-[var(--color-border)] text-[var(--color-text-dim)] tracking-wider">
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
                <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
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
                      <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider">hit rate</p>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-3 pt-1">
                    <div>
                      <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">hits</p>
                      <p className="text-xs font-light tabular-nums text-[var(--color-success)]">{cacheStats.hits}</p>
                    </div>
                    <div>
                      <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">miss</p>
                      <p className="text-xs font-light tabular-nums text-[var(--color-text-muted)]">{cacheStats.misses}</p>
                    </div>
                    <div>
                      <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">size</p>
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
