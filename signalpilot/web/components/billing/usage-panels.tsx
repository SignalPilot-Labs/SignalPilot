"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AllowanceUse, DailyUsagePoint, UnitConsumption } from "~/lib/backend-client";
import { UNIT_LABELS, creditsToUsd, formatCredits, formatUsd } from "~/lib/billing-rates";
import { ALLOTMENT_BAR_COLOR, INCLUDED_USAGE_COPY, splitAllotment } from "~/lib/allotment";

// ---------------------------------------------------------------------------
// Credit balance bar. Past the included credits the bar stays full in its
// normal colour and the excess is shown as extra usage; it is not an error.
// ---------------------------------------------------------------------------

export function CreditBalanceCard({
  granted,
  consumed,
  available,
  overage,
  periodEnd,
}: {
  granted: number;
  consumed: number;
  available: number;
  overage: number;
  periodEnd: string;
}) {
  const split = splitAllotment(consumed, granted);
  const percentage = Math.round(split.fillPct);
  // The period end is a UTC calendar boundary; render it as a UTC date.
  const resetStr = new Date(periodEnd).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });

  return (
    <div
      data-testid="credit-balance"
      className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-5 mb-6 card-accent-top"
    >
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] text-[var(--color-text-muted)] uppercase tracking-[0.08em]">
          credits this period
        </span>
        <span className="text-[13px] font-mono tabular-nums text-[var(--color-text)]">
          {percentage}%
        </span>
      </div>

      <div
        role="progressbar"
        aria-valuenow={consumed}
        aria-valuemin={0}
        aria-valuemax={Math.max(granted, consumed)}
        aria-label={`${formatCredits(consumed)} of ${formatCredits(granted)} included credits consumed`}
        className="h-1.5 bg-[var(--color-border)] w-full mb-3 rounded-full overflow-hidden"
      >
        <div
          className="h-full transition-all duration-500"
          style={{ width: `${split.fillPct}%`, backgroundColor: ALLOTMENT_BAR_COLOR }}
        />
      </div>

      <div className="flex items-center justify-between text-[12px]">
        <span className="text-[var(--color-text-dim)]">
          <span className="font-mono tabular-nums text-[var(--color-text-muted)]">
            {formatCredits(consumed)}
          </span>{" "}
          of <span className="font-mono tabular-nums">{formatCredits(granted)}</span> credits used
          {overage > 0 && (
            <>
              {" · "}
              <span data-testid="usage-extra" className="text-[var(--color-text)]">
                Extra usage:{" "}
                <span className="font-mono tabular-nums">
                  {formatCredits(overage)} credits ({formatUsd(creditsToUsd(overage))})
                </span>
              </span>
            </>
          )}
        </span>
        <span className="text-[var(--color-text-dim)]">
          <span className="font-mono tabular-nums text-[var(--color-text-muted)]">
            {formatCredits(Math.max(available, 0))}
          </span>{" "}
          left · resets{" "}
          <span className="text-[var(--color-text-muted)] font-mono tabular-nums">{resetStr}</span>
        </span>
      </div>
      {overage > 0 && (
        <p data-testid="usage-included-copy" className="mt-2 text-[12px] text-[var(--color-text-dim)]">
          {INCLUDED_USAGE_COPY}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stat tiles
// ---------------------------------------------------------------------------

export function StatTile({
  label,
  value,
  sub,
  tone = "default",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "default" | "success" | "warning" | "error";
}) {
  const color = tone === "default" ? "var(--color-text)" : `var(--color-${tone})`;
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-4">
      <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em] mb-1">
        {label}
      </p>
      <p className="text-lg font-mono tabular-nums" style={{ color }}>{value}</p>
      {sub && <p className="text-[11px] text-[var(--color-text-dim)] mt-0.5">{sub}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Consumption by unit
// ---------------------------------------------------------------------------

function formatQuantity(quantity: number): string {
  return Number.isInteger(quantity)
    ? quantity.toLocaleString("en-US")
    : quantity.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** Credits consumed per unit this period, from `consumed_by_unit` on the usage summary. */
export function ConsumptionByUnitTable({ byUnit }: { byUnit: Record<string, UnitConsumption> }) {
  const rows = Object.entries(byUnit)
    .map(([unit, c]) => ({ unit, credits: Math.abs(c.credits), quantity: c.quantity, rows: c.rows }))
    .filter((r) => r.credits > 0)
    .sort((a, b) => b.credits - a.credits);

  if (rows.length === 0) {
    return (
      <p className="p-5 text-[12px] text-[var(--color-text-dim)]">
        nothing consumed yet this period.
      </p>
    );
  }

  return (
    <table className="w-full text-[12px]">
      <thead>
        <tr className="border-b border-[var(--color-border)] bg-[var(--color-bg)]">
          <th className="text-left px-5 py-2 text-[11px] font-normal text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
            unit
          </th>
          <th className="text-right px-5 py-2 text-[11px] font-normal text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
            quantity
          </th>
          <th className="text-right px-5 py-2 text-[11px] font-normal text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
            credits
          </th>
          <th className="text-right px-5 py-2 text-[11px] font-normal text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
            usd
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.unit} data-testid={`unit-${r.unit}`} className="border-b border-[var(--color-border)] last:border-b-0">
            <td className="px-5 py-2.5 text-[var(--color-text-muted)]">
              {UNIT_LABELS[r.unit] ?? r.unit}
            </td>
            <td className="px-5 py-2.5 text-right font-mono tabular-nums text-[var(--color-text-dim)]">
              {formatQuantity(r.quantity)}
            </td>
            <td className="px-5 py-2.5 text-right font-mono tabular-nums text-[var(--color-text)]">
              {formatCredits(r.credits)}
            </td>
            <td className="px-5 py-2.5 text-right font-mono tabular-nums text-[var(--color-text-dim)]">
              {formatUsd(creditsToUsd(r.credits))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------------------
// Allowance meters — seats, models, eval runs are counters, not credits.
// Beyond the allowance is metered, not an error: same colour, full bar.
// ---------------------------------------------------------------------------

export function AllowanceMeter({
  label,
  use,
  beyondNote,
}: {
  label: string;
  use: AllowanceUse;
  beyondNote: string;
}) {
  const split = splitAllotment(use.used, use.included);
  const over = Math.round(split.extra);
  const pct = split.fillPct;

  return (
    <div
      data-testid={`allowance-${label.replace(/\s+/g, "-")}`}
      className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-4"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
          {label}
        </span>
        <span className="text-[12px] font-mono tabular-nums text-[var(--color-text)]">
          {use.used.toLocaleString()} / {use.included.toLocaleString()}
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={use.used}
        aria-valuemin={0}
        aria-valuemax={use.included}
        aria-label={`${label}: ${use.used} of ${use.included} included`}
        className="h-1 bg-[var(--color-border)] w-full rounded-full overflow-hidden"
      >
        <div className="h-full" style={{ width: `${pct}%`, backgroundColor: ALLOTMENT_BAR_COLOR }} />
      </div>
      <p className="text-[11px] text-[var(--color-text-dim)] mt-2">
        {over > 0 ? `${over.toLocaleString()} beyond allowance, ${beyondNote}` : "within allowance"}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Daily consumption chart
// ---------------------------------------------------------------------------

function DailyTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ value: number; payload: DailyUsagePoint }>;
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload;
  const units = Object.entries(point.by_unit ?? {})
    .filter(([, v]) => Math.abs(v) > 0)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  return (
    <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-[10px] px-3 py-2">
      <p className="text-[11px] text-[var(--color-text-dim)] mb-0.5 font-mono">{label}</p>
      <p className="text-[13px] tabular-nums text-[var(--color-text)] font-mono">
        {formatCredits(payload[0].value)} credits
      </p>
      {units.map(([unit, v]) => (
        <p key={unit} className="text-[11px] text-[var(--color-text-dim)] font-mono tabular-nums">
          {UNIT_LABELS[unit] ?? unit}: {formatCredits(Math.abs(v))}
        </p>
      ))}
    </div>
  );
}

export function DailyConsumptionChart({ points }: { points: DailyUsagePoint[] }) {
  const data = points.map((p) => ({
    ...p,
    credits: Math.abs(p.credits),
    label: p.date.length >= 10 ? p.date.slice(5) : p.date,
  }));
  const hasData = data.some((p) => p.credits > 0);

  if (!hasData) {
    return (
      <div className="h-[200px] flex items-center justify-center">
        <p className="text-[12px] text-[var(--color-text-dim)]">
          no consumption yet this period
        </p>
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fontSize: 10, fill: "var(--color-text-dim)", fontFamily: "monospace" }}
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
        />
        <YAxis
          tick={{ fontSize: 10, fill: "var(--color-text-dim)", fontFamily: "monospace" }}
          tickLine={false}
          axisLine={false}
          width={48}
        />
        <Tooltip content={<DailyTooltip />} cursor={{ fill: "var(--color-bg-hover)" }} />
        <Bar dataKey="credits" fill="var(--color-success)" radius={[2, 2, 0, 0]} maxBarSize={24} />
      </BarChart>
    </ResponsiveContainer>
  );
}
