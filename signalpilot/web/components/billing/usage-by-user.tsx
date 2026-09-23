"use client";

// Per-user consumption: the admin table from `usage/by-user` and the period
// selector. Pure rendering; the page owns the fetches.

import type { UsageByUserRow } from "~/lib/backend-client";
import { creditsToUsd, formatCredits, formatUsd } from "~/lib/billing-rates";

export interface PeriodOption {
  /** YYYY-MM-01, what the backend takes as `period`. */
  value: string;
  /** "Sep 2026" */
  label: string;
}

/** The open month first, then `months - 1` earlier ones, all UTC calendar months. */
export function periodOptions(months = 6, now: Date = new Date()): PeriodOption[] {
  const out: PeriodOption[] = [];
  const year = now.getUTCFullYear();
  const month = now.getUTCMonth();
  for (let i = 0; i < months; i++) {
    const d = new Date(Date.UTC(year, month - i, 1));
    const value = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-01`;
    const label = d.toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
    out.push({ value, label });
  }
  return out;
}

export function PeriodSelector({
  value,
  options,
  onChange,
}: {
  value: string;
  options: PeriodOption[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)]">
      period
      <select
        aria-label="billing period"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="px-2 py-1 bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[8px] text-[12px] text-[var(--color-text)] focus:outline-none focus:border-[var(--color-text-dim)]"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

const SYSTEM_LABEL = "System / scheduled";

function formatCount(n: number): string {
  return new Intl.NumberFormat("en-US").format(Math.round(n));
}

function displayName(row: UsageByUserRow): string {
  if (row.user_id === null) return row.name || SYSTEM_LABEL;
  return row.name || row.email || row.user_id;
}

const TH = "px-4 py-2 text-[11px] font-normal text-[var(--color-text-dim)] uppercase tracking-[0.08em] whitespace-nowrap";
const TD_NUM = "px-4 py-2.5 text-right font-mono tabular-nums text-[var(--color-text-dim)]";

/** Admin view: one row per user, credits first. */
export function UsageByUserTable({ rows }: { rows: UsageByUserRow[] }) {
  const sorted = [...rows].sort((a, b) => Math.abs(b.credits_consumed) - Math.abs(a.credits_consumed));
  if (sorted.length === 0) {
    return (
      <p className="p-5 text-[12px] text-[var(--color-text-dim)]" data-testid="usage-by-user-empty">
        nobody consumed credits in this period.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12px]" data-testid="usage-by-user-table">
        <thead>
          <tr className="border-b border-[var(--color-border)] bg-[var(--color-bg)]">
            <th className={`text-left ${TH}`}>user</th>
            <th className={`text-right ${TH}`}>credits</th>
            <th className={`text-right ${TH}`}>usd</th>
            <th className={`text-right ${TH}`}>threads</th>
            <th className={`text-right ${TH}`}>queries</th>
            <th className={`text-right ${TH}`}>tokens in</th>
            <th className={`text-right ${TH}`}>tokens out</th>
            <th className={`text-right ${TH}`}>cache read</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const credits = Math.abs(row.credits_consumed);
            return (
              <tr
                key={row.user_id ?? "__system"}
                data-testid={`usage-user-${row.user_id ?? "system"}`}
                className="border-b border-[var(--color-border)] last:border-b-0"
              >
                <td className="px-4 py-2.5">
                  <div className="text-[var(--color-text-muted)]">{displayName(row)}</div>
                  {row.user_id !== null && row.email && row.name ? (
                    <div className="text-[11px] text-[var(--color-text-dim)]">{row.email}</div>
                  ) : null}
                </td>
                <td className={`${TD_NUM} text-[var(--color-text)]`}>{formatCredits(credits)}</td>
                <td className={TD_NUM}>{formatUsd(creditsToUsd(credits))}</td>
                <td className={TD_NUM}>{formatCount(row.threads)}</td>
                <td className={TD_NUM}>{formatCount(row.queries)}</td>
                <td className={TD_NUM}>{formatCount(row.tokens_in)}</td>
                <td className={TD_NUM}>{formatCount(row.tokens_out)}</td>
                <td className={TD_NUM}>{formatCount(row.tokens_cache_read)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
