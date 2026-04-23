"use client";

import { useEffect, useState } from "react";
import { BarChart3, Key, AlertTriangle } from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { useAppAuth } from "@/lib/auth-context";
import { useBackendClient } from "@/lib/backend-client";
import type { UsageSummaryResponse, DailyUsagePoint, KeyUsageEntry } from "@/lib/backend-client";
import { useSubscription } from "@/lib/subscription-context";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { SectionHeader } from "@/components/ui/section-header";
import { StatusDot } from "@/components/ui/data-viz";
import { TimeAgo } from "@/components/ui/time-ago";
import { useToast } from "@/components/ui/toast";
import { UsageSkeleton } from "@/components/ui/skeleton";
import {
  generateDailyUsage,
  generateKeyUsage,
  getRateLimitStatus,
} from "@/lib/mock-usage";

// ---------------------------------------------------------------------------
// Custom recharts tooltip
// ---------------------------------------------------------------------------

function UsageTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ value: number }>;
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] px-3 py-2">
      <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider mb-0.5 font-mono">
        {label}
      </p>
      <p className="text-[13px] font-light tabular-nums text-[var(--color-text)] font-mono">
        {payload[0].value.toLocaleString()} requests
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rate limit bar — accepts UsageSummaryResponse (real or mock-mapped)
// ---------------------------------------------------------------------------

function RateLimitCard({ summary }: { summary: UsageSummaryResponse }) {
  const percentage = summary.daily_limit > 0
    ? Math.round((summary.daily_used / summary.daily_limit) * 100)
    : 0;

  const barColor =
    percentage < 50
      ? "var(--color-success)"
      : percentage < 80
        ? "var(--color-warning)"
        : "var(--color-error)";

  const textColor =
    percentage < 50
      ? "text-[var(--color-success)]"
      : percentage < 80
        ? "text-[var(--color-warning)]"
        : "text-[var(--color-error)]";

  const resetDate = new Date(summary.daily_reset_at);
  const resetTimeStr = resetDate.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 mb-6 card-accent-top">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <StatusDot
            status={
              percentage < 50
                ? "healthy"
                : percentage < 80
                  ? "warning"
                  : "error"
            }
            size={4}
          />
          <span className="text-[12px] text-[var(--color-text-muted)] uppercase tracking-[0.15em]">
            daily rate limit
          </span>
        </div>
        <span className={`text-[13px] font-light tabular-nums ${textColor}`}>
          {percentage}%
        </span>
      </div>

      {/* Progress bar */}
      <div
        role="progressbar"
        aria-valuenow={summary.daily_used}
        aria-valuemin={0}
        aria-valuemax={summary.daily_limit}
        aria-label={`Rate limit: ${summary.daily_used} of ${summary.daily_limit} requests used today`}
        className="h-1.5 bg-[var(--color-border)] w-full mb-3 overflow-hidden"
      >
        <div
          className="h-full transition-all duration-500"
          style={{
            width: `${Math.min(percentage, 100)}%`,
            backgroundColor: barColor,
          }}
        />
      </div>

      <div className="flex items-center justify-between text-[12px] tracking-wider">
        <span className="text-[var(--color-text-dim)]">
          <span className="tabular-nums text-[var(--color-text-muted)]">
            {summary.daily_used.toLocaleString()}
          </span>{" "}
          of{" "}
          <span className="tabular-nums">{summary.daily_limit.toLocaleString()}</span> requests
        </span>
        <span className="text-[var(--color-text-dim)]">
          resets at{" "}
          <span className="text-[var(--color-text-muted)] tabular-nums">{resetTimeStr}</span>
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-key breakdown row — uses KeyUsageEntry (backend shape)
// ---------------------------------------------------------------------------

function KeyUsageRow({ entry }: { entry: KeyUsageEntry }) {
  return (
    <div className="flex items-center gap-4 px-5 py-3 border-b border-[var(--color-border)] hover:bg-[var(--color-bg-hover)] transition-colors">
      {/* Key name */}
      <div className="flex-1 min-w-0">
        <span className="text-xs text-[var(--color-text-muted)] tracking-wider truncate block">
          {entry.key_name}
        </span>
      </div>

      {/* Key ID prefix */}
      <code className="text-[12px] text-[var(--color-text-dim)] tracking-wider w-28 flex-shrink-0 truncate">
        {entry.key_id.slice(0, 8)}…
      </code>

      {/* Total requests */}
      <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider w-24 flex-shrink-0 tabular-nums">
        {entry.total_requests.toLocaleString()}
      </span>

      {/* Last 7 days */}
      <span className="text-[12px] text-[var(--color-success)] tracking-wider w-20 flex-shrink-0 tabular-nums">
        {entry.last_7d.toLocaleString()}
      </span>

      {/* Last used */}
      <div className="w-28 flex-shrink-0">
        {entry.last_used_at ? (
          <TimeAgo
            timestamp={new Date(entry.last_used_at).getTime()}
            className="text-[12px] text-[var(--color-text-dim)] tracking-wider tabular-nums"
          />
        ) : (
          <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider">—</span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-key table header
// ---------------------------------------------------------------------------

function KeyUsageTableHeader() {
  return (
    <div className="flex items-center gap-4 px-5 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
      <span className="flex-1 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
        key name
      </span>
      <span className="w-28 flex-shrink-0 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
        key id
      </span>
      <span className="w-24 flex-shrink-0 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
        total req
      </span>
      <span className="w-20 flex-shrink-0 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
        last 7d
      </span>
      <span className="w-28 flex-shrink-0 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
        last used
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Content — safe to call useBackendClient() here (guarded by Gate)
// ---------------------------------------------------------------------------

function UsageContent() {
  const client = useBackendClient();
  const { planTier } = useSubscription();
  const { toast } = useToast();

  const [summary, setSummary] = useState<UsageSummaryResponse | null>(null);
  const [dailyData, setDailyData] = useState<DailyUsagePoint[] | null>(null);
  const [keyStats, setKeyStats] = useState<KeyUsageEntry[] | null>(null);
  const [usingMock, setUsingMock] = useState(false);

  useEffect(() => {
    let cancelled = false;

    Promise.all([
      client.getUsageSummary(),
      client.getUsageDaily(30),
      client.getUsageByKey(),
    ])
      .then(([summaryData, dailyRes, byKeyRes]) => {
        if (cancelled) return;
        setSummary(summaryData);
        setDailyData(dailyRes.points);
        setKeyStats(
          [...byKeyRes.keys].sort((a, b) => b.total_requests - a.total_requests),
        );
        setUsingMock(false);
      })
      .catch(() => {
        if (cancelled) return;
        // Fall back to mock data — map to backend shapes
        const mockRateLimit = getRateLimitStatus(planTier);
        const mockKeys = client.getApiKeys().catch(() => []);
        mockKeys.then((keys) => {
          if (cancelled) return;
          const mockDaily = generateDailyUsage(keys, 30);
          const mockKeyStats: KeyUsageEntry[] = keys.map((k) => {
            const stats = generateKeyUsage(k);
            return {
              key_id: stats.keyId,
              key_name: stats.keyName,
              total_requests: stats.totalRequests,
              last_7d: stats.last7Days,
              last_used_at: stats.lastUsedAt,
            };
          });

          const mockSummary: UsageSummaryResponse = {
            total_requests: mockKeyStats.reduce((sum, s) => sum + s.total_requests, 0),
            total_requests_today: mockRateLimit.used,
            total_requests_7d: mockKeyStats.reduce((sum, s) => sum + s.last_7d, 0),
            total_requests_30d: mockKeyStats.reduce((sum, s) => sum + s.total_requests, 0),
            daily_limit: mockRateLimit.limit,
            daily_used: mockRateLimit.used,
            daily_reset_at: mockRateLimit.resetAt,
            active_keys: mockKeyStats.filter((s) => s.last_7d > 0).length,
            last_activity_at: mockKeyStats.reduce<string | null>((latest, s) => {
              if (!latest || !s.last_used_at) return latest ?? s.last_used_at;
              return s.last_used_at > latest ? s.last_used_at : latest;
            }, null),
          };

          setSummary(mockSummary);
          setDailyData(mockDaily);
          setKeyStats(
            [...mockKeyStats].sort((a, b) => b.total_requests - a.total_requests),
          );
          setUsingMock(true);
        }).catch((e) => {
          if (!cancelled) toast(String(e), "error");
        });
      });

    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planTier]);

  if (summary === null || dailyData === null || keyStats === null) {
    return <UsageSkeleton />;
  }

  const hasData = keyStats.length > 0;

  return (
    <div className="p-8 max-w-4xl animate-fade-in">
      <PageHeader
        title="usage"
        subtitle="analytics"
        description="api request usage and rate limits"
      />

      <TerminalBar
        path="settings/usage --stats"
        status={<StatusDot status={hasData ? "healthy" : "unknown"} size={4} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            keys:{" "}
            <code className="text-[12px] text-[var(--color-text)]">{keyStats.length}</code>
          </span>
          <span className="text-[var(--color-text-dim)]">
            plan:{" "}
            <code className="text-[12px] text-[var(--color-text)]">{planTier}</code>
          </span>
          {usingMock && (
            <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider opacity-60">
              (mock data)
            </span>
          )}
        </div>
      </TerminalBar>

      {/* Rate limit status */}
      <RateLimitCard summary={summary} />

      {/* Daily usage chart */}
      <section className="mb-8">
        <SectionHeader icon={BarChart3} title="daily usage — last 30 days" />
        <div
          className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4"
          role="img"
          aria-label="Daily API usage chart, last 30 days"
        >
          {hasData ? (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart
                data={dailyData}
                margin={{ top: 4, right: 4, bottom: 0, left: 0 }}
              >
                <CartesianGrid
                  stroke="var(--color-border)"
                  strokeDasharray="3 3"
                  vertical={false}
                />
                <XAxis
                  dataKey="date"
                  tick={{
                    fontSize: 10,
                    fill: "var(--color-text-dim)",
                    fontFamily: "monospace",
                  }}
                  tickLine={false}
                  axisLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{
                    fontSize: 10,
                    fill: "var(--color-text-dim)",
                    fontFamily: "monospace",
                  }}
                  tickLine={false}
                  axisLine={false}
                  width={48}
                />
                <Tooltip content={<UsageTooltip />} cursor={{ fill: "var(--color-bg-hover)" }} />
                <Bar
                  dataKey="requests"
                  fill="var(--color-success)"
                  radius={[2, 2, 0, 0]}
                  maxBarSize={24}
                />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[200px] flex items-center justify-center">
              <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
                no usage data — create api keys to start tracking
              </p>
            </div>
          )}
        </div>
      </section>

      {/* Per-key breakdown */}
      <section>
        <SectionHeader icon={Key} title="per-key breakdown" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
          {keyStats.length === 0 ? (
            <div className="flex items-start gap-3 p-5">
              <AlertTriangle
                className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0"
                strokeWidth={1.5}
              />
              <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
                no api keys found. create keys in the{" "}
                <a
                  href="/settings/api-keys"
                  className="text-[var(--color-text-muted)] underline hover:text-[var(--color-text)] transition-colors"
                >
                  api keys
                </a>{" "}
                settings to see per-key usage here.
              </p>
            </div>
          ) : (
            <>
              <KeyUsageTableHeader />
              {keyStats.map((entry) => (
                <KeyUsageRow key={entry.key_id} entry={entry} />
              ))}
            </>
          )}
        </div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Gate — checks isCloudMode before rendering Content
// ---------------------------------------------------------------------------

export default function UsagePage() {
  const { isCloudMode, isLoaded } = useAppAuth();

  if (!isLoaded) {
    return <UsageSkeleton />;
  }

  if (!isCloudMode) {
    return (
      <div className="p-8 max-w-4xl animate-fade-in">
        <PageHeader
          title="usage"
          subtitle="analytics"
          description="api request usage and rate limits"
        />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6 flex items-start gap-3">
          <AlertTriangle
            className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0"
            strokeWidth={1.5}
          />
          <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
            usage analytics is available in cloud mode. set{" "}
            <code className="text-[var(--color-text-muted)]">
              NEXT_PUBLIC_DEPLOYMENT_MODE=cloud
            </code>{" "}
            and configure clerk to enable this feature.
          </p>
        </div>
      </div>
    );
  }

  return <UsageContent />;
}
