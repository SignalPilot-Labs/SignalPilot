"use client";

/**
 * Pieces shared by the usage pages (/settings/usage, /me, /members).
 * Usage amounts are neutral facts: nothing here uses the error token.
 */

import type { ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import type { UsageDays } from "~/lib/api/usage";
import type { DailyUsage, UsageTotals } from "~/lib/types";
import { formatCompact, formatCount, formatUsd } from "~/lib/usage-format";
import { DailyUsageCharts } from "./daily-usage-charts";

export const USAGE_PERIODS: UsageDays[] = [7, 30, 90];

export const USAGE_TAB_OVERVIEW = { label: "Overview", href: "/settings/usage" };
export const USAGE_TAB_ME = { label: "My usage", href: "/settings/usage/me" };
export const USAGE_TAB_MEMBERS = { label: "Members", href: "/settings/usage/members" };

/**
 * Tab row for every usage page. The overview (org credit ledger) and the
 * members table are admin-only; a member has one page, "my usage".
 */
export function usageTabs(isAdmin: boolean) {
  return isAdmin ? [USAGE_TAB_OVERVIEW, USAGE_TAB_ME, USAGE_TAB_MEMBERS] : [USAGE_TAB_ME];
}

// ---------------------------------------------------------------------------
// Period selector
// ---------------------------------------------------------------------------

export function PeriodSelector({
  value,
  onChange,
}: {
  value: UsageDays;
  onChange: (days: UsageDays) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="usage period"
      className="inline-flex items-center gap-1 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-card)] p-0.5"
    >
      {USAGE_PERIODS.map((d) => {
        const active = d === value;
        return (
          <button
            key={d}
            type="button"
            role="radio"
            aria-checked={active}
            data-testid={`usage-period-${d}`}
            onClick={() => onChange(d)}
            className={`px-3 py-1 rounded-full text-[12px] font-mono tabular-nums transition-colors ${
              active
                ? "bg-[var(--color-bg-elevated)] border border-[var(--color-border-hover)] text-[var(--color-text)]"
                : "border border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
            }`}
          >
            {d}d
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Totals row (stat tiles)
// ---------------------------------------------------------------------------

function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] px-4 py-3 min-w-0">
      <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em] mb-1 truncate">
        {label}
      </p>
      <p className="text-[18px] font-mono tabular-nums text-[var(--color-text)] leading-tight truncate">
        {value}
      </p>
      {hint ? (
        <p className="text-[11px] text-[var(--color-text-dim)] mt-0.5 truncate">{hint}</p>
      ) : null}
    </div>
  );
}

export function TotalsRow({ totals }: { totals: UsageTotals }) {
  return (
    <div
      data-testid="usage-totals"
      className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6"
    >
      <StatTile label="chat runs" value={formatCount(totals.chat_runs)} hint={`${formatCount(totals.conversations)} conversations`} />
      <StatTile label="cost" value={formatUsd(totals.cost_usd)} hint="extra cost is billed" />
      <StatTile label="tokens in" value={formatCompact(totals.input_tokens)} hint={`${formatCompact(totals.cache_read_tokens)} cache read`} />
      <StatTile label="tokens out" value={formatCompact(totals.output_tokens)} />
      <StatTile label="queries" value={formatCount(totals.queries)} hint={`${formatCount(totals.blocked_queries)} blocked`} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Daily chart section
// ---------------------------------------------------------------------------

export function DailySection({ daily, days }: { daily: DailyUsage[]; days: number }) {
  const hasData = daily.some((d) => d.chat_runs > 0 || d.cost_usd > 0 || d.queries > 0);
  return (
    <section className="mb-8">
      <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em] mb-3">
        daily activity, last {days} days
      </p>
      {hasData ? (
        <DailyUsageCharts daily={daily} />
      ) : (
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] h-[180px] flex items-center justify-center">
          <p className="text-[12px] text-[var(--color-text-dim)]">no activity in this period</p>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Table primitives (flex rows, matching the per-key table on /settings/usage)
// ---------------------------------------------------------------------------

export function TableShell({ children }: { children: ReactNode }) {
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] overflow-x-auto">
      {children}
    </div>
  );
}

export function TableHeaderRow({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-4 px-5 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)] min-w-max">
      {children}
    </div>
  );
}

export function TableRow({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div
      data-testid={testId}
      className="flex items-center gap-4 px-5 py-3 border-b border-[var(--color-border)] last:border-b-0 hover:bg-[var(--color-bg-hover)] transition-colors min-w-max"
    >
      {children}
    </div>
  );
}

export function HeaderCell({
  children,
  width,
  grow,
  sortable,
  active,
  onClick,
}: {
  children: ReactNode;
  width?: string;
  grow?: boolean;
  sortable?: boolean;
  active?: boolean;
  onClick?: () => void;
}) {
  const cls = `${grow ? "flex-1 min-w-[160px]" : `${width ?? "w-20"} flex-shrink-0`} text-[11px] uppercase tracking-[0.08em] text-left ${
    active ? "text-[var(--color-text)]" : "text-[var(--color-text-dim)]"
  }`;
  if (sortable) {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-sort={active ? "descending" : "none"}
        className={`${cls} hover:text-[var(--color-text)] transition-colors`}
      >
        {children}
        {active ? " ▾" : ""}
      </button>
    );
  }
  return <span className={cls}>{children}</span>;
}

export function Cell({
  children,
  width,
  grow,
  mono = true,
}: {
  children: ReactNode;
  width?: string;
  grow?: boolean;
  mono?: boolean;
}) {
  return (
    <span
      className={`${grow ? "flex-1 min-w-[160px]" : `${width ?? "w-20"} flex-shrink-0`} text-[12px] text-[var(--color-text-dim)] truncate ${
        mono ? "font-mono tabular-nums" : ""
      }`}
    >
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Notices
// ---------------------------------------------------------------------------

export function Notice({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div
      data-testid={testId}
      className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-5 flex items-start gap-3"
    >
      <AlertTriangle
        className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0"
        strokeWidth={1.5}
      />
      <p className="text-[12px] text-[var(--color-text-dim)] leading-relaxed">{children}</p>
    </div>
  );
}

export function EmptyRows({ children }: { children: ReactNode }) {
  return (
    <div className="px-5 py-6 text-[12px] text-[var(--color-text-dim)]">{children}</div>
  );
}
