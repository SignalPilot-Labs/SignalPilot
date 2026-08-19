"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ElementType } from "react";
import useSWR from "swr";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  BookOpenText,
  Bot,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  Database,
  FileChartColumn,
  Gauge,
  MessageSquareText,
  Play,
  ShieldCheck,
  ShieldX,
  Zap,
} from "lucide-react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  getEvalAccuracy,
  getEvalAvailability,
  getProjects,
  listStandaloneConversations,
  subscribeMetrics,
  type EvalAccuracyPoint,
  type EvalRegression,
} from "~/lib/api";
import {
  prefetchCommonData,
  useAudit,
  useAuditStats,
  useBudgets,
  useConnections,
  useConnectionsHealth,
  useKnowledgeUsage,
  usePlan,
  useReports,
} from "~/lib/hooks/use-gateway-data";
import type { AuditEntry, MetricsSnapshot } from "~/lib/types";
import { useAppAuth } from "~/lib/auth-context";
import { DashboardSkeleton } from "~/components/ui/skeleton";
import { TimeAgo } from "~/components/ui/time-ago";
import { useOnboardingStatus } from "~/lib/onboarding";
import "./dashboard.css";

type ActivityPoint = {
  label: string;
  operations: number;
  blocked: number;
  cost: number;
};

type AttentionItem = {
  title: string;
  detail: string;
  href: string;
  tone: "warning" | "critical";
};

function timestampMs(value: number): number {
  return value < 10_000_000_000 ? value * 1000 : value;
}

function formatMoney(value: number): string {
  if (value === 0) return "$0.00";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function percentile(values: number[], ratio: number): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * ratio))];
}

function buildActivitySeries(entries: AuditEntry[]): ActivityPoint[] {
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const points = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(now);
    date.setDate(now.getDate() - (6 - index));
    return {
      date,
      key: date.toISOString().slice(0, 10),
      label: date.toLocaleDateString("en-US", { weekday: "short" }),
      operations: 0,
      blocked: 0,
      cost: 0,
    };
  });
  const pointMap = new Map(points.map((point) => [point.key, point]));
  entries.forEach((entry) => {
    const key = new Date(timestampMs(entry.timestamp)).toISOString().slice(0, 10);
    const point = pointMap.get(key);
    if (!point) return;
    point.operations += 1;
    if (entry.blocked) point.blocked += 1;
    point.cost += entry.cost_usd ?? 0;
  });
  return points.map(({ label, operations, blocked, cost }) => ({
    label,
    operations,
    blocked,
    cost: Number(cost.toFixed(4)),
  }));
}

function Metric({
  label,
  value,
  note,
  icon: Icon,
  tone = "neutral",
}: {
  label: string;
  value: string;
  note: string;
  icon: ElementType;
  tone?: "neutral" | "good" | "warning" | "critical";
}) {
  return (
    <div className={`dash-metric is-${tone}`}>
      <div><Icon aria-hidden="true" /><span>{label}</span></div>
      <strong>{value}</strong>
      <p>{note}</p>
    </div>
  );
}

function ActivityTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: Array<{ dataKey: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="dash-chart-tooltip">
      <strong>{label}</strong>
      {payload.map((item) => (
        <span key={item.dataKey}>
          <i style={{ background: item.color }} />
          {item.dataKey === "cost" ? `${formatMoney(item.value)} estimated` : `${item.value} ${item.dataKey}`}
        </span>
      ))}
    </div>
  );
}

function QualityGauge({ value }: { value: number | null }) {
  const score = Math.max(0, Math.min(100, value ?? 0));
  const circumference = 2 * Math.PI * 34;
  return (
    <div className="dash-quality-gauge" aria-label={value == null ? "No accuracy data" : `${value.toFixed(0)} percent accuracy`}>
      <svg viewBox="0 0 80 80" aria-hidden="true">
        <circle cx="40" cy="40" r="34" className="track" />
        <circle
          cx="40"
          cy="40"
          r="34"
          className="value"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - score / 100)}
        />
      </svg>
      <div><strong>{value == null ? "--" : value.toFixed(0)}</strong>{value != null && <span>%</span>}</div>
    </div>
  );
}

function SurfaceSignal({
  href,
  icon: Icon,
  label,
  value,
  note,
  tone = "neutral",
}: {
  href: string;
  icon: ElementType;
  label: string;
  value: string;
  note: string;
  tone?: "neutral" | "good" | "warning";
}) {
  return (
    <Link href={href} className={`dash-surface-signal is-${tone}`}>
      <div className="dash-surface-icon"><Icon aria-hidden="true" /></div>
      <div><span>{label}</span><strong>{value}</strong><p>{note}</p></div>
      <ArrowUpRight aria-hidden="true" />
    </Link>
  );
}

function DashboardOnboardingCheck() {
  const router = useRouter();
  const { activeOrgId, isAuthenticated } = useAppAuth();
  const { isComplete, isLoading, markComplete } = useOnboardingStatus();
  const [autoCompleting, setAutoCompleting] = useState(false);
  const triedRef = useRef(false);

  useEffect(() => {
    if (isLoading || autoCompleting || !isAuthenticated || isComplete === true || triedRef.current) return;
    if (activeOrgId) {
      triedRef.current = true;
      setAutoCompleting(true);
      markComplete().catch(() => {}).finally(() => setAutoCompleting(false));
    } else {
      router.push("/onboarding");
    }
  }, [activeOrgId, autoCompleting, isAuthenticated, isComplete, isLoading, markComplete, router]);

  if (isLoading || autoCompleting || (isComplete === false && !activeOrgId)) return <DashboardSkeleton />;
  return <DashboardContent />;
}

export default function DashboardGate() {
  const { isCloudMode, isLoaded } = useAppAuth();
  if (!isLoaded) return <DashboardSkeleton />;
  return isCloudMode ? <DashboardOnboardingCheck /> : <DashboardContent />;
}

function DashboardContent() {
  const { isCloudMode, user } = useAppAuth();
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const { data: auditData } = useAudit({ limit: 500 });
  const { data: auditTotals } = useAuditStats();
  const { data: budgetData } = useBudgets();
  const { data: connectionData } = useConnections();
  const { data: healthData } = useConnectionsHealth();
  const { data: plan } = usePlan();
  const { data: knowledgeUsage } = useKnowledgeUsage();
  const { data: reports } = useReports();
  const { data: projects } = useSWR("dashboard-projects", getProjects, { dedupingInterval: 30_000 });
  const { data: conversationsData } = useSWR(
    "dashboard-conversations",
    listStandaloneConversations,
    { refreshInterval: 30_000, shouldRetryOnError: false },
  );
  const { data: evalAvailability } = useSWR("dashboard-eval-availability", getEvalAvailability, { dedupingInterval: 60_000 });
  const { data: evalAccuracy } = useSWR(
    evalAvailability?.enabled ? "dashboard-eval-accuracy" : null,
    getEvalAccuracy,
    { refreshInterval: 30_000 },
  );

  useEffect(() => { prefetchCommonData(); }, []);
  useEffect(() => subscribeMetrics(setMetrics), []);

  const entries = auditData?.entries ?? [];
  const connections = connectionData ?? [];
  const health = healthData?.connections ?? [];
  const conversations = conversationsData?.conversations ?? [];
  const activitySeries = useMemo(() => buildActivitySeries(entries), [entries]);
  const latestAccuracy = useMemo<EvalAccuracyPoint | null>(() => {
    const history = evalAccuracy?.history ?? [];
    return [...history].sort((left, right) => right.created_at.localeCompare(left.created_at))[0] ?? null;
  }, [evalAccuracy]);
  const latestRegression = useMemo<EvalRegression | null>(() => {
    const regressions = evalAccuracy?.regressions ?? [];
    return [...regressions].sort((left, right) => right.created_at.localeCompare(left.created_at))[0] ?? null;
  }, [evalAccuracy]);

  const healthyConnections = health.filter((item) => item.status === "healthy").length;
  const unhealthyConnections = health.filter((item) => ["warning", "degraded", "unhealthy"].includes(item.status)).length;
  const pendingConnections = Math.max(0, connections.length - healthyConnections - unhealthyConnections);
  const durationValues = entries.flatMap((entry) => entry.duration_ms == null ? [] : [entry.duration_ms]);
  const p95Latency = percentile(durationValues, 0.95);
  const recentCost = entries.reduce((sum, entry) => sum + (entry.cost_usd ?? 0), 0);
  const trackedSpend = budgetData?.total_spent_usd ?? 0;
  const budgetSessions = (budgetData?.sessions ?? []) as Array<Record<string, unknown>>;
  const activeBudgetTotal = budgetSessions.reduce((sum, session) => sum + Number(session.budget_usd ?? 0), 0);
  const activeBudgetSpent = budgetSessions.reduce((sum, session) => sum + Number(session.spent_usd ?? 0), 0);
  const budgetUtilization = activeBudgetTotal ? activeBudgetSpent / activeBudgetTotal * 100 : 0;
  const chatActualSpend = conversations.reduce((sum, item) => sum + item.actual_spend_usd, 0);
  const chatReservedSpend = conversations.reduce((sum, item) => sum + item.reserved_spend_usd, 0);
  const runningChats = conversations.filter((item) => ["queued", "running", "waiting_for_user", "waiting_for_query_approval"].includes(item.run_status ?? "")).length;
  const activeWorkloads = runningChats + (metrics?.running_sandboxes ?? 0);
  const allTimeEvents = auditTotals?.total ?? auditData?.total ?? entries.length;
  const blockedEvents = auditTotals?.blocked ?? entries.filter((entry) => entry.blocked).length;
  const blockRate = allTimeEvents ? blockedEvents / allTimeEvents * 100 : 0;
  const requestsToday = plan?.usage.queries_today ?? 0;
  const dailyLimit = plan?.limits.queries_per_day;
  const dailyUsagePct = typeof dailyLimit === "number" && dailyLimit > 0 ? requestsToday / dailyLimit * 100 : null;
  const storagePct = knowledgeUsage?.storage_limit_bytes
    ? knowledgeUsage.active_bytes / knowledgeUsage.storage_limit_bytes * 100
    : 0;

  const attentionItems = useMemo<AttentionItem[]>(() => {
    const items: AttentionItem[] = [];
    if (unhealthyConnections) {
      items.push({
        title: `${unhealthyConnections} connection${unhealthyConnections === 1 ? "" : "s"} need attention`,
        detail: "Health checks report degraded or failing access.",
        href: "/connections",
        tone: "critical",
      });
    }
    if (latestRegression) {
      items.push({
        title: `${latestRegression.drop_pct.toFixed(1)} point eval regression`,
        detail: `${latestRegression.flipped_tasks.length} tasks changed outcome in the latest regression.`,
        href: `/evals?run=${latestRegression.run_id}`,
        tone: "critical",
      });
    }
    if (latestAccuracy?.coverage_pct != null && latestAccuracy.coverage_pct < 80) {
      items.push({
        title: `${latestAccuracy.coverage_pct.toFixed(0)}% mart coverage`,
        detail: "Production marts remain outside the current eval set.",
        href: "/evals/accuracy",
        tone: "warning",
      });
    }
    if (budgetUtilization >= 80) {
      items.push({
        title: `${budgetUtilization.toFixed(0)}% of active budgets used`,
        detail: "Review session limits before workloads are stopped.",
        href: "/settings/usage",
        tone: "warning",
      });
    }
    if (dailyUsagePct != null && dailyUsagePct >= 80 && dailyLimit != null) {
      items.push({
        title: `${dailyUsagePct.toFixed(0)}% of daily query allowance used`,
        detail: `${requestsToday.toLocaleString()} of ${dailyLimit.toLocaleString()} queries used today.`,
        href: "/settings/usage",
        tone: "warning",
      });
    }
    return items.slice(0, 4);
  }, [budgetUtilization, dailyLimit, dailyUsagePct, latestAccuracy, latestRegression, requestsToday, unhealthyConnections]);

  const state = attentionItems.length
    ? { label: "Attention required", tone: "warning", title: "Operating signals need review" }
    : !connections.length
      ? { label: "Setup required", tone: "neutral", title: "Connect a warehouse to activate your workspace" }
      : { label: "Operating normally", tone: "good", title: "Agents are operating within policy" };

  return (
    <main className="dash-page">
      <header className="dash-header">
        <div>
          <span className="dash-eyebrow">Workspace command center</span>
          <h1>Dashboard</h1>
          <p>{isCloudMode && user?.email ? `${user.email} · ` : ""}Usage, cost, quality, and governance across every agent workflow.</p>
        </div>
        <div className="dash-actions">
          <Link href="/chats" className="dash-action is-secondary"><MessageSquareText /> Ask data</Link>
          {evalAvailability?.enabled && <Link href="/evals" className="dash-action is-primary"><Play /> Run eval</Link>}
        </div>
      </header>

      <section className="dash-command-band">
        <div className="dash-command-state">
          <span className={`dash-state is-${state.tone}`}><i /> {state.label}</span>
          <h2>{state.title}</h2>
          <p>
            {connections.length
              ? `${healthyConnections} healthy · ${unhealthyConnections} unhealthy · ${pendingConnections} pending · ${allTimeEvents.toLocaleString()} governed events`
              : "Add a governed connection to start measuring agent activity."}
          </p>
        </div>
        <div className="dash-command-metrics">
          <Metric label="Queries today" value={requestsToday.toLocaleString()} note={typeof dailyLimit === "number" ? `${dailyLimit.toLocaleString()} daily allowance` : "Unlimited plan"} icon={Zap} tone="good" />
          <Metric label="Tracked spend" value={formatMoney(trackedSpend)} note={`${budgetSessions.length} active session budgets`} icon={CircleDollarSign} tone={budgetUtilization >= 80 ? "warning" : "neutral"} />
          <Metric label="Eval accuracy" value={latestAccuracy ? `${latestAccuracy.accuracy_pct.toFixed(0)}%` : "--"} note={latestAccuracy ? `${latestAccuracy.tasks_passed}/${latestAccuracy.tasks_total} tasks passed` : "No completed eval run"} icon={Gauge} tone={latestAccuracy && latestAccuracy.accuracy_pct >= 85 ? "good" : latestAccuracy ? "warning" : "neutral"} />
          <Metric label="Policy blocks" value={blockedEvents.toLocaleString()} note={`${blockRate.toFixed(1)}% of governed events`} icon={ShieldX} tone={blockedEvents ? "warning" : "good"} />
          <Metric label="Active workloads" value={activeWorkloads.toLocaleString()} note={`${runningChats} chats · ${metrics?.running_sandboxes ?? 0} sandboxes`} icon={Bot} />
        </div>
      </section>

      <section className="dash-operations-grid">
        <div className="dash-panel dash-activity-panel">
          <div className="dash-panel-head">
            <div><span className="dash-eyebrow">Governed usage</span><h2>Operations and estimated cost</h2><p>Latest 500-event window, grouped across the last seven days.</p></div>
            <div className="dash-chart-legend"><span><i className="ops" /> operations</span><span><i className="blocks" /> blocked</span><span><i className="cost" /> estimated cost</span></div>
          </div>
          <div className="dash-chart-wrap">
            <ResponsiveContainer width="100%" height={260}>
              <ComposedChart data={activitySeries} margin={{ top: 16, right: 4, left: -24, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--color-border)" strokeDasharray="2 6" />
                <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fill: "var(--color-text-dim)", fontSize: 10 }} />
                <YAxis yAxisId="events" allowDecimals={false} axisLine={false} tickLine={false} tick={{ fill: "var(--color-text-dim)", fontSize: 10 }} />
                <YAxis yAxisId="cost" orientation="right" axisLine={false} tickLine={false} tick={{ fill: "var(--color-text-dim)", fontSize: 10 }} tickFormatter={(value) => `$${value}`} />
                <Tooltip content={<ActivityTooltip />} cursor={{ fill: "var(--color-bg-hover)" }} />
                <Bar yAxisId="events" dataKey="operations" fill="#4f9d8d" radius={[3, 3, 0, 0]} maxBarSize={34} />
                <Bar yAxisId="events" dataKey="blocked" fill="#d76166" radius={[3, 3, 0, 0]} maxBarSize={12} />
                <Line yAxisId="cost" type="monotone" dataKey="cost" stroke="#d1a54a" strokeWidth={2} dot={{ r: 2, fill: "#d1a54a" }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="dash-chart-footer">
            <span><strong>{allTimeEvents.toLocaleString()}</strong> lifetime events</span>
            <span><strong>{p95Latency == null ? "--" : `${Math.round(p95Latency)}ms`}</strong> p95 latency</span>
            <span><strong>{formatMoney(recentCost)}</strong> recent estimated cost</span>
          </div>
        </div>

        <aside className="dash-panel dash-cost-panel">
          <div className="dash-panel-head"><div><span className="dash-eyebrow">Cost control</span><h2>Spend and budget position</h2><p>Persisted gateway and data-chat cost signals.</p></div></div>
          <div className="dash-cost-total"><span>Total tracked spend</span><strong>{formatMoney(trackedSpend)}</strong><small>Across all governed budget sessions</small></div>
          <div className="dash-budget-meter">
            <div><span>Active budget use</span><strong>{activeBudgetTotal ? `${budgetUtilization.toFixed(0)}%` : "--"}</strong></div>
            <div className="dash-meter"><i style={{ width: `${Math.min(100, budgetUtilization)}%` }} /></div>
            <p>{formatMoney(activeBudgetSpent)} used of {formatMoney(activeBudgetTotal)} allocated</p>
          </div>
          <dl className="dash-cost-breakdown">
            <div><dt>Recent query estimate</dt><dd>{formatMoney(recentCost)}</dd></div>
            <div><dt>Data chat actual</dt><dd>{formatMoney(chatActualSpend)}</dd></div>
            <div><dt>Data chat reserved</dt><dd>{formatMoney(chatReservedSpend)}</dd></div>
          </dl>
          <Link href="/settings/usage" className="dash-panel-link">Usage details <ArrowUpRight /></Link>
        </aside>
      </section>

      <section className="dash-surface-grid" aria-label="Product signals">
        <div className="dash-quality-signal">
          <QualityGauge value={latestAccuracy?.accuracy_pct ?? null} />
          <div><span>Agent quality</span><strong>{latestAccuracy ? `${latestAccuracy.tasks_passed} of ${latestAccuracy.tasks_total} tasks passed` : "Awaiting first eval"}</strong><p>{latestAccuracy?.coverage_pct == null ? "No mart coverage baseline" : `${latestAccuracy.coverage_pct.toFixed(0)}% mart coverage`}</p></div>
          <Link href="/evals/accuracy" aria-label="Open accuracy"><ArrowUpRight /></Link>
        </div>
        <SurfaceSignal href="/connections" icon={Database} label="Data access" value={`${connections.length} connections`} note={pendingConnections ? `${pendingConnections} awaiting health samples · ${projects?.length ?? 0} projects` : `${healthyConnections} healthy · ${projects?.length ?? 0} projects`} tone={unhealthyConnections ? "warning" : healthyConnections ? "good" : "neutral"} />
        <SurfaceSignal href="/knowledge" icon={BookOpenText} label="Knowledge" value={`${knowledgeUsage?.active_docs ?? 0} active entries`} note={`${storagePct.toFixed(1)}% of storage used`} tone={knowledgeUsage?.active_docs ? "good" : "neutral"} />
        <SurfaceSignal href="/chats" icon={MessageSquareText} label="Data chat" value={`${conversations.length} conversations`} note={`${runningChats} active · ${formatMoney(chatActualSpend)} spent`} tone={runningChats ? "good" : "neutral"} />
        <SurfaceSignal href="/reports" icon={FileChartColumn} label="Reports" value={`${reports?.length ?? 0} published`} note="Reusable governed outputs" />
      </section>

      <section className="dash-lower-grid">
        <div className="dash-panel dash-feed-panel">
          <div className="dash-panel-head">
            <div><span className="dash-eyebrow">Audit stream</span><h2>Recent governed activity</h2><p>Queries, tool calls, and policy decisions across the workspace.</p></div>
            <Link href="/audit" className="dash-panel-link">Full audit <ArrowUpRight /></Link>
          </div>
          <div className="dash-activity-feed">
            {!entries.length && <div className="dash-feed-empty"><Activity /><strong>No activity yet</strong><span>Run a governed query to start the audit stream.</span></div>}
            {entries.slice(0, 8).map((entry) => (
              <div className="dash-activity-row" key={entry.id}>
                <span className={`dash-event-mark${entry.blocked ? " is-blocked" : ""}`}><i /></span>
                <div>
                  <strong>{entry.blocked ? "Policy blocked an operation" : entry.event_type.replaceAll("_", " ")}</strong>
                  <span>{entry.connection_name ?? entry.agent_id ?? "workspace"}</span>
                </div>
                <code>{entry.sql?.slice(0, 72) ?? String(entry.metadata?.tool_name ?? entry.metadata?.code_preview ?? "governed operation")}</code>
                <span className="dash-row-metric">{entry.duration_ms == null ? "--" : `${Math.round(entry.duration_ms)}ms`}</span>
                <TimeAgo timestamp={entry.timestamp} live />
              </div>
            ))}
          </div>
        </div>

        <aside className="dash-panel dash-attention-panel">
          <div className="dash-panel-head"><div><span className="dash-eyebrow">Attention queue</span><h2>What needs action</h2><p>Operational and quality signals above their thresholds.</p></div></div>
          <div className="dash-attention-list">
            {!attentionItems.length && (
              <div className="dash-all-clear"><CheckCircle2 /><strong>No critical issues</strong><span>Current operating signals are within policy.</span></div>
            )}
            {attentionItems.map((item) => (
              <Link href={item.href} key={item.title} className={`dash-attention-item is-${item.tone}`}>
                {item.tone === "critical" ? <AlertTriangle /> : <Clock3 />}
                <div><strong>{item.title}</strong><span>{item.detail}</span></div>
                <ArrowUpRight />
              </Link>
            ))}
          </div>
          <div className="dash-governance-state"><ShieldCheck /><div><strong>Governance active</strong><span>SQL policy, PII controls, audit, and budget enforcement</span></div></div>
        </aside>
      </section>
    </main>
  );
}
