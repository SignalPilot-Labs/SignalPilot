"use client";

// The org overview of /settings/usage (admins), read from the credit ledger on
// the billing backend. Members use the gateway-backed /settings/usage/me page.

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, BarChart3, Coins, Gauge, RefreshCw, Users } from "lucide-react";
import { useBackendClient } from "~/lib/backend-client";
import type { DailyUsagePoint, UsageByUserRow, UsageSummaryResponse } from "~/lib/backend-client";
import {
  DEFAULT_RATE_CARD,
  centsToUsd,
  creditsToUsd,
  formatCredits,
  formatUsd,
} from "~/lib/billing-rates";
import { PageHeader, TerminalBar } from "~/components/ui/page-header";
import { SectionHeader } from "~/components/ui/section-header";
import { StatusDot } from "~/components/ui/data-viz";
import { UsageSkeleton } from "~/components/ui/skeleton";
import {
  AllowanceMeter,
  ConsumptionByUnitTable,
  CreditBalanceCard,
  DailyConsumptionChart,
  StatTile,
} from "~/components/billing/usage-panels";
import { PeriodSelector, UsageByUserTable, periodOptions } from "~/components/billing/usage-by-user";

export type UsageTab = { label: string; href: string };

/** The overview header; `tabs` links the sibling usage pages (/me, /members). */
export function usageHeader(tabs?: UsageTab[]) {
  return (
    <PageHeader
      title="usage"
      subtitle="credits"
      description="credits granted, consumed and returned this billing period"
      tabs={tabs}
    />
  );
}

// Billing periods are UTC calendar boundaries (midnight UTC). Format them as
// UTC dates so a viewer west of Greenwich does not see "Aug 31" for Sep 1.
function formatPeriod(start: string, end: string): string {
  const fmt = (v: string) =>
    new Date(v).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  return `${fmt(start)} – ${fmt(end)}`;
}

// ---------------------------------------------------------------------------
// Error state — the backend is the ledger; there is nothing to show without it
// ---------------------------------------------------------------------------

export function UsageError({
  message,
  onRetry,
  header,
}: {
  message: string;
  onRetry: () => void;
  header?: React.ReactNode;
}) {
  return (
    <div className="p-8 max-w-4xl animate-fade-in">
      {header ?? usageHeader()}
      <div
        data-testid="usage-error"
        className="border border-[var(--color-error)]/30 bg-[var(--color-bg-card)] rounded-[14px] p-6 space-y-3"
      >
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-3.5 h-3.5 text-[var(--color-error)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
          <div className="space-y-1">
            <p className="text-[12px] text-[var(--color-text)]">usage is unavailable</p>
            <p className="text-[12px] text-[var(--color-text-dim)] leading-relaxed">
              the billing backend could not be reached, so there is no ledger to show.
            </p>
            <p className="text-[11px] text-[var(--color-text-dim)] font-mono break-all">{message}</p>
          </div>
        </div>
        <button
          onClick={onRetry}
          className="flex items-center gap-2 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-colors duration-150"
        >
          <RefreshCw className="w-3 h-3" />
          retry
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-user section (admin) — its own fetch so the period can change alone
// ---------------------------------------------------------------------------

function UsageByUserSection() {
  const client = useBackendClient();
  const options = useMemo(() => periodOptions(6), []);
  const [period, setPeriod] = useState(options[0].value);
  const [rows, setRows] = useState<UsageByUserRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setError(null);
    client
      .getUsageByUser(period)
      .then((data) => {
        if (!cancelled) setRows(data.rows ?? []);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [client, period]);

  return (
    <section className="mb-8" data-testid="usage-by-user-section">
      <div className="flex items-center justify-between mb-4">
        <SectionHeader icon={Users} title="by user" />
        <PeriodSelector value={period} options={options} onChange={setPeriod} />
      </div>
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] overflow-hidden">
        {error ? (
          <p className="p-5 text-[12px] text-[var(--color-error)] font-mono break-all">{error}</p>
        ) : rows === null ? (
          <p className="p-5 text-[12px] text-[var(--color-text-dim)]" aria-busy="true">
            loading…
          </p>
        ) : (
          <UsageByUserTable rows={rows} />
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Org view — admins: totals, allowances, daily chart, by unit, by user.
// Going past the included credits is normal usage, not an error: meters fill
// in their usual colour and the excess reads as extra cost (lib/allotment).
// ---------------------------------------------------------------------------

export function OrgUsageContent({ tabs }: { tabs?: UsageTab[] }) {
  const client = useBackendClient();
  const [summary, setSummary] = useState<UsageSummaryResponse | null>(null);
  const [daily, setDaily] = useState<DailyUsagePoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => {
    setError(null);
    setSummary(null);
    setDaily(null);
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([client.getUsageSummary(), client.getUsageDaily(31)])
      .then(([summaryData, dailyData]) => {
        if (cancelled) return;
        setSummary(summaryData);
        setDaily(dailyData.points);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [client, attempt]);

  if (error) return <UsageError message={error} onRetry={retry} header={usageHeader(tabs)} />;
  if (summary === null || daily === null) return <UsageSkeleton />;

  const granted = summary.granted + summary.purchased + summary.returned;
  const consumed = Math.abs(summary.consumed);

  return (
    <div className="p-8 max-w-4xl animate-fade-in" data-testid="org-usage">
      {usageHeader(tabs)}

      <TerminalBar path="settings/usage --period" status={<StatusDot status="healthy" size={4} />}>
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            plan: <code className="text-[12px] text-[var(--color-text)]">{summary.plan_tier}</code>
          </span>
          <span className="text-[var(--color-text-dim)]">
            period:{" "}
            <code className="text-[12px] text-[var(--color-text)]">
              {formatPeriod(summary.period_start, summary.period_end)}
            </code>
          </span>
          <span className="text-[var(--color-text-dim)]">
            included:{" "}
            <code className="text-[12px] text-[var(--color-text)]">{formatCredits(summary.included_credits)}</code>
          </span>
        </div>
      </TerminalBar>

      <CreditBalanceCard
        granted={granted}
        consumed={consumed}
        available={summary.available}
        overage={summary.overage}
        periodEnd={summary.period_end}
      />

      <section className="mb-8">
        <SectionHeader icon={Coins} title="credits" />
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatTile label="granted" value={formatCredits(summary.granted)} sub="included this period" />
          <StatTile label="consumed" value={formatCredits(consumed)} sub={formatUsd(creditsToUsd(consumed))} />
          <StatTile
            label="returned"
            value={formatCredits(summary.returned)}
            sub="guarantees and reversals"
            tone={summary.returned > 0 ? "success" : "default"}
          />
          <StatTile label="available" value={formatCredits(Math.max(summary.available, 0))} />
          <StatTile
            label="extra usage"
            value={formatCredits(summary.overage)}
            sub={summary.overage > 0 ? `${formatUsd(centsToUsd(summary.overage_cents))} on next invoice` : "none"}
          />
        </div>
      </section>

      <section className="mb-8">
        <SectionHeader icon={Gauge} title="allowances" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <AllowanceMeter label="seats" use={summary.allowances.seats} beyondNote="metered daily in credits" />
          <AllowanceMeter
            label="covered models"
            use={summary.allowances.models}
            beyondNote={`${formatCredits(DEFAULT_RATE_CARD.model_month_credits)} credits per model-month`}
          />
          <AllowanceMeter
            label="eval runs"
            use={summary.allowances.eval_runs}
            beyondNote={`${formatCredits(DEFAULT_RATE_CARD.eval_run_credits)} credits per run`}
          />
        </div>
      </section>

      <section className="mb-8">
        <SectionHeader icon={BarChart3} title="daily consumption" />
        <div
          className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-4"
          role="img"
          aria-label="Daily credit consumption chart for the current billing period"
        >
          <DailyConsumptionChart points={daily} />
        </div>
      </section>

      <section className="mb-8">
        <SectionHeader icon={Coins} title="consumed by unit" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] overflow-hidden">
          <ConsumptionByUnitTable byUnit={summary.consumed_by_unit} />
        </div>
      </section>

      <UsageByUserSection />
    </div>
  );
}
