"use client";

import { AlertTriangle, ArrowDownRight, ArrowUpRight, CheckCircle2, Users, Zap } from "lucide-react";
import type { PaidTier, PlanInfo } from "~/lib/backend-client";
import { TIER_RANK, type EntitlementTier } from "~/lib/entitlement";
import { formatCredits } from "~/lib/billing-rates";
import { formatPrice, monthlyFeeCents, monthlyPrice } from "~/lib/billing-plan-review";

export { formatPrice } from "~/lib/billing-plan-review";

type AllowancePlan = Pick<
  PlanInfo,
  "included_seats" | "included_models" | "included_eval_runs" | "included_credits"
>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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
    `${plan.included_seats.toLocaleString("en-US")} seats`,
    `${plan.included_models.toLocaleString("en-US")} covered models${more}`,
    `${plan.included_eval_runs.toLocaleString("en-US")} eval runs per month`,
    `${formatCredits(plan.included_credits)} credits per month${more}`,
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
// Plan card — Team and Scale. One published monthly price for everyone;
// seats and credits are reviewed in the dialog on click.
// ---------------------------------------------------------------------------

export function PlanCard({
  plan,
  currentTier,
  pendingDowngradeTo,
  pendingDowngradeDate,
  onSelect,
  disabled = false,
}: {
  plan: PlanInfo;
  currentTier: string;
  pendingDowngradeTo?: string | null;
  pendingDowngradeDate?: string | null;
  onSelect: (plan: PlanInfo) => void;
  disabled?: boolean;
}) {
  const color = tierAccent(plan.tier);
  const Icon = plan.tier === "scale" ? Zap : Users;

  const isCurrent = plan.tier === currentTier;
  const isHigher = rank(plan.tier) > rank(currentTier);
  const isPendingDowngrade = pendingDowngradeTo === plan.tier;
  const monthly = monthlyPrice(plan);
  const hasPrice = monthly !== null;
  const currency = monthly?.currency ?? "usd";

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
            <span
              data-testid="plan-price"
              className="text-xl font-bold font-mono tracking-tight tabular-nums"
              style={{ color }}
            >
              {formatPrice(monthlyFeeCents(plan), currency)}
            </span>
            <span className="text-[12px] text-[var(--color-text-dim)]">/mo</span>
          </div>
          <span className="text-[11px] text-[var(--color-text-dim)] font-mono tabular-nums">
            billed monthly
          </span>
        </div>
      </div>

      <p className="text-[12px] text-[var(--color-text-dim)] leading-relaxed mb-4">{plan.description}</p>

      <AllowanceList plan={plan} color={color} />

      {isCurrent ? (
        <div
          data-testid="plan-current"
          className="w-full flex items-center justify-center gap-2 px-4 py-2 text-[12px] border rounded-[10px]"
          style={{ borderColor: color, color, opacity: 0.7 }}
        >
          <CheckCircle2 className="w-3 h-3" />
          Current plan
        </div>
      ) : isPendingDowngrade && pendingDowngradeDate ? (
        <div
          className="w-full flex items-center justify-center gap-2 px-4 py-2 text-[12px] border rounded-[10px] border-[var(--color-warning)]/40 text-[var(--color-warning)]"
          style={{ opacity: 0.8 }}
        >
          <AlertTriangle className="w-3 h-3" />
          Active{" "}
          {new Date(pendingDowngradeDate + "T00:00:00").toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
          })}
        </div>
      ) : (
        <button
          data-testid="plan-select"
          onClick={() => onSelect(plan)}
          disabled={!hasPrice || disabled}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 text-[12px] border rounded-[10px] transition-colors duration-150 disabled:opacity-40 hover:bg-[var(--color-bg-hover)]"
          style={{ borderColor: color, color }}
        >
          {isHigher ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
          {isHigher ? "Upgrade" : "Downgrade"}
        </button>
      )}
    </div>
  );
}
