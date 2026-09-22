"use client";

import type { PlanInfo } from "~/lib/backend-client";
import { PlanCard } from "~/components/billing/plan-card";
import { EnterpriseCard } from "~/components/billing/enterprise-card";

/**
 * The plan cards row. Every visitor sees the same published prices; an org
 * on Enterprise sees only the enterprise card, because it cannot self-serve
 * into or out of its contract.
 */
export function PlanGrid({
  plans,
  currentTier,
  pendingDowngradeTo,
  pendingDowngradeDate,
  onSelect,
  disabled = false,
}: {
  plans: PlanInfo[];
  currentTier: string;
  pendingDowngradeTo?: string | null;
  pendingDowngradeDate?: string | null;
  onSelect: (plan: PlanInfo) => void;
  disabled?: boolean;
}) {
  const isEnterprise = currentTier === "enterprise";
  const selfServe = isEnterprise ? [] : plans.filter((p) => p.tier !== "enterprise");
  const enterprisePlan = plans.find((p) => p.tier === "enterprise") ?? null;

  return (
    <div data-testid="plan-grid" className="flex flex-col md:flex-row gap-4">
      {selfServe.map((p) => (
        <PlanCard
          key={p.tier}
          plan={p}
          currentTier={currentTier}
          pendingDowngradeTo={pendingDowngradeTo}
          pendingDowngradeDate={pendingDowngradeDate}
          onSelect={onSelect}
          disabled={disabled}
        />
      ))}
      <EnterpriseCard plan={enterprisePlan} isCurrent={isEnterprise} />
    </div>
  );
}
