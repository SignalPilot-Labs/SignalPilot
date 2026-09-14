"use client";

import { ArrowRight, Lock } from "lucide-react";
import Link from "next/link";
import { useSubscription } from "~/lib/subscription-context";
import { tierLabel } from "~/lib/entitlement";

/**
 * The one plan gate in the UI. A free org sees every feature in the
 * navigation; the working surface is replaced by this prompt, which links to
 * the plan cards. Nothing here checks tier names: the only question is
 * whether the org is on a billable plan.
 */
export function PlanRequired({
  feature,
  description,
  compact = false,
}: {
  /** Short name of the surface being gated, e.g. "evals". */
  feature: string;
  /** One sentence on what the feature does. */
  description?: string;
  /** Inline variant for panels inside an otherwise available page. */
  compact?: boolean;
}) {
  const { tier, status } = useSubscription();
  const pastDue = status === "past_due";

  const card = (
    <div
      data-testid="plan-required"
      className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-6 space-y-4"
    >
      <div className="flex items-center gap-2">
        <Lock className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
        <span className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
          plan required
        </span>
      </div>
      <p className="text-sm text-[var(--color-text)]">
        {pastDue
          ? `Your subscription is past due, so ${feature} is paused.`
          : `${capitalize(feature)} is part of every paid plan.`}
      </p>
      {description && (
        <p className="text-xs text-[var(--color-text-dim)] leading-relaxed">{description}</p>
      )}
      <p className="text-xs text-[var(--color-text-dim)] leading-relaxed">
        Your organization is on the {tierLabel(tier)} plan.{" "}
        {pastDue
          ? "Update your payment method to restore access."
          : "Choose Team, Scale or Enterprise to turn it on; nothing runs and nothing is metered until you do."}
      </p>
      <Link
        href="/settings/billing"
        className="inline-flex items-center gap-2 px-5 py-3 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium rounded-[10px] transition-colors duration-150 hover:opacity-90"
      >
        {pastDue ? "Manage billing" : "See plans"}
        <ArrowRight className="w-3 h-3" />
      </Link>
    </div>
  );

  if (compact) return card;

  return (
    <div className="p-8 animate-fade-in">
      <div className="max-w-md mx-auto mt-24">{card}</div>
    </div>
  );
}

function capitalize(value: string): string {
  return value ? value[0].toUpperCase() + value.slice(1) : value;
}
