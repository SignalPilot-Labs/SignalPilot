"use client";

import { AlertTriangle, ArrowRight, CheckCircle2, Loader2, Users, Zap } from "lucide-react";
import type { PaidTier, PlanInfo, PlanPrice } from "~/lib/backend-client";
import { TIER_RANK, type EntitlementTier } from "~/lib/entitlement";
import { formatCredits } from "~/lib/billing-rates";

type AllowancePlan = Pick<
  PlanInfo,
  | "included_seats"
  | "included_models"
  | "included_eval_runs"
  | "included_credits"
  | "seat_month_credits"
  | "managed_from_cents"
>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function formatPrice(amount: number, currency: string): string {
  const dollars = amount / 100;
  const hasCents = dollars % 1 !== 0;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: hasCents ? 2 : 0,
    maximumFractionDigits: hasCents ? 2 : 0,
  }).format(dollars);
}

export function getMonthlyEquivalent(price: PlanPrice): number {
  if (price.interval === "year") return Math.round(price.amount / 12);
  return price.amount;
}

/** Accent per tier; the backend publishes no presentation hints. */
const TIER_ACCENT: Record<PaidTier, string> = {
  team: "var(--color-success)",
  scale: "var(--color-warning)",
  enterprise: "var(--color-text-muted)",
};

export function tierAccent(tier: string): string {
  return TIER_ACCENT[tier as PaidTier] ?? TIER_ACCENT.enterprise;
}

function rank(tier: string): number {
  return TIER_RANK[tier as EntitlementTier] ?? 0;
}

// ---------------------------------------------------------------------------
// Billing interval toggle
// ---------------------------------------------------------------------------

export function IntervalToggle({
  interval,
  onChange,
}: {
  interval: "month" | "year";
  onChange: (v: "month" | "year") => void;
}) {
  const cls = (active: boolean) =>
    `px-3 py-1.5 text-[11px] border rounded-[10px] transition-colors duration-150 ${
      active
        ? "border-[var(--color-text-muted)] text-[var(--color-text)]"
        : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
    }`;
  return (
    <div className="flex items-center gap-2 mb-5">
      <button onClick={() => onChange("year")} className={cls(interval === "year")}>
        annual
      </button>
      <button onClick={() => onChange("month")} className={cls(interval === "month")}>
        month-to-month
        <span className="ml-1.5 text-[var(--color-text-dim)]">+25%</span>
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Allowance list shared by the plan and enterprise cards
// ---------------------------------------------------------------------------

export function AllowanceList({
  plan,
  color,
  moreByAgreement = false,
}: {
  plan: AllowancePlan;
  color: string;
  moreByAgreement?: boolean;
}) {
  const more = moreByAgreement ? ", more by agreement" : "";
  const items = [
    `${plan.included_seats.toLocaleString()} seats included`,
    `${plan.included_models.toLocaleString()} covered models${more}`,
    `${plan.included_eval_runs.toLocaleString()} eval runs per month`,
    `${formatCredits(plan.included_credits)} credits per month${more}`,
    `added seats ${formatCredits(plan.seat_month_credits)} credits per seat-month`,
    `managed from ${formatPrice(plan.managed_from_cents, "usd")}/mo`,
  ];
  return (
    <ul className="space-y-2 mb-4">
      {items.map((f) => (
        <li key={f} className="flex items-center gap-2">
          <CheckCircle2 className="w-3 h-3 flex-shrink-0" style={{ color }} strokeWidth={1.5} />
          <span className="text-[12px] text-[var(--color-text-muted)]">{f}</span>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Plan card — Team and Scale, fully dynamic from the backend
// ---------------------------------------------------------------------------

export function PlanCard({
  plan,
  interval,
  currentTier,
  pendingDowngradeTo,
  pendingDowngradeDate,
  onUpgrade,
  upgrading,
}: {
  plan: PlanInfo;
  interval: "month" | "year";
  currentTier: string;
  pendingDowngradeTo?: string | null;
  pendingDowngradeDate?: string | null;
  onUpgrade: (priceId: string) => void;
  upgrading: string | null;
}) {
  const color = tierAccent(plan.tier);
  const price = plan.prices.find((p) => p.interval === interval) ?? plan.prices[0] ?? null;
  const Icon = plan.tier === "scale" ? Zap : Users;

  const isUpgrading = price !== null && upgrading === price.price_id;
  const isCurrent = plan.tier === currentTier;
  const isHigher = rank(plan.tier) > rank(currentTier);
  const isLower = rank(plan.tier) < rank(currentTier);
  const isPendingDowngrade = pendingDowngradeTo === plan.tier;
  // The Stripe price for the chosen interval; the published flat fee when
  // Stripe has not been configured with one yet.
  const monthlyEquiv = price ? getMonthlyEquivalent(price) : plan.monthly_fee_cents;
  const currency = price?.currency ?? "usd";

  return (
    <div
      data-testid={`plan-card-${plan.tier}`}
      className="flex-1 border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-5 hover:border-[var(--color-border-hover)] transition-colors duration-150"
      style={{ borderTopColor: color, borderTopWidth: "2px" }}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon className="w-3.5 h-3.5" style={{ color }} strokeWidth={1.5} />
          <span className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
            {plan.name || plan.tier}
          </span>
        </div>
        <div className="text-right">
          <div className="flex items-baseline gap-0.5">
            <span className="text-xl font-bold font-mono tracking-tight tabular-nums" style={{ color }}>
              {formatPrice(monthlyEquiv, currency)}
            </span>
            <span className="text-[12px] text-[var(--color-text-dim)]">/mo</span>
          </div>
          <span className="text-[11px] text-[var(--color-text-dim)] font-mono tabular-nums">
            {price === null
              ? "flat fee"
              : price.interval === "year"
                ? `${formatPrice(price.amount, price.currency)}/yr, billed annually`
                : "billed monthly"}
          </span>
        </div>
      </div>

      <p className="text-[12px] text-[var(--color-text-dim)] leading-relaxed mb-4">
        {plan.description}
      </p>

      <AllowanceList plan={plan} color={color} />

      {isCurrent ? (
        <div
          className="w-full flex items-center justify-center gap-2 px-4 py-2 text-[12px] border rounded-[10px]"
          style={{ borderColor: color, color, opacity: 0.7 }}
        >
          <CheckCircle2 className="w-3 h-3" />
          current plan
        </div>
      ) : isPendingDowngrade && pendingDowngradeDate ? (
        <div
          className="w-full flex items-center justify-center gap-2 px-4 py-2 text-[12px] border rounded-[10px] border-[var(--color-warning)]/40 text-[var(--color-warning)]"
          style={{ opacity: 0.8 }}
        >
          <AlertTriangle className="w-3 h-3" />
          active{" "}
          {new Date(pendingDowngradeDate + "T00:00:00").toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
          })}
        </div>
      ) : (
        <button
          onClick={() => price && onUpgrade(price.price_id)}
          disabled={price === null || isUpgrading || upgrading !== null}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 text-[12px] border rounded-[10px] transition-colors duration-150 disabled:opacity-40 hover:bg-[var(--color-bg-hover)]"
          style={{ borderColor: color, color }}
        >
          {isUpgrading ? <Loader2 className="w-3 h-3 animate-spin" /> : <ArrowRight className="w-3 h-3" />}
          {isUpgrading
            ? "redirecting..."
            : isHigher
              ? `upgrade to ${plan.tier}`
              : isLower
                ? `downgrade to ${plan.tier}`
                : `switch to ${plan.tier}`}
        </button>
      )}
    </div>
  );
}
