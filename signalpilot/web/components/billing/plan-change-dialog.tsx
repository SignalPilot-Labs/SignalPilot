"use client";

import { Loader2 } from "lucide-react";
import type { PlanInfo, PlanPrice } from "~/lib/backend-client";
import { ConfirmDialog } from "~/components/ui/confirm-dialog";
import { formatPrice } from "~/components/billing/plan-card";

export interface ProrationPreview {
  amount_due: number;
  currency: string;
  credit: number;
  new_charge: number;
  immediate: boolean;
  effective_date: string | null;
}

export interface PendingPlanChange {
  priceId: string;
  plan: PlanInfo;
  price: PlanPrice;
  isUpgrade: boolean;
  proration: ProrationPreview | null;
  loadingPreview: boolean;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-[var(--color-border)]">
      <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">{label}</span>
      {children}
    </div>
  );
}

function ProrationBody({ change }: { change: PendingPlanChange }) {
  if (change.loadingPreview) {
    return (
      <div className="flex items-center gap-2 py-2">
        <Loader2 className="w-3 h-3 text-[var(--color-text-dim)] animate-spin" />
        <span className="text-[11px] text-[var(--color-text-dim)]">calculating...</span>
      </div>
    );
  }
  const p = change.proration;
  if (!p) {
    return (
      <p className="text-[11px] text-[var(--color-text-dim)] leading-relaxed">
        the prorated difference will be charged immediately.
      </p>
    );
  }
  if (p.immediate) {
    return (
      <>
        {p.credit > 0 && (
          <Row label="credit from current plan">
            <span className="text-[12px] text-[var(--color-success)] font-mono tabular-nums">
              −{formatPrice(p.credit, p.currency)}
            </span>
          </Row>
        )}
        <Row label="charge today">
          <span className="text-[13px] font-medium font-mono tabular-nums text-[var(--color-text)]">
            {formatPrice(p.amount_due, p.currency)}
          </span>
        </Row>
      </>
    );
  }
  return (
    <div className="py-2 space-y-2">
      <p className="text-[11px] text-[var(--color-text-dim)] leading-relaxed">
        your current plan stays active until the end of this billing period. no charge today.
      </p>
      {p.effective_date && (
        <p className="text-[11px] text-[var(--color-error)] leading-relaxed">
          your plan will change to {change.plan.tier} on{" "}
          {new Date(p.effective_date + "T00:00:00").toLocaleDateString("en-US", {
            month: "long",
            day: "numeric",
            year: "numeric",
          })}
        </p>
      )}
    </div>
  );
}

/** Paid-to-paid plan change confirmation with the proration preview. */
export function PlanChangeDialog({
  change,
  onConfirm,
  onCancel,
}: {
  change: PendingPlanChange | null;
  onConfirm: (priceId: string) => void;
  onCancel: () => void;
}) {
  return (
    <ConfirmDialog
      open={change !== null}
      title={change?.isUpgrade ? "upgrade plan" : "change plan"}
      message={change ? `${change.isUpgrade ? "Upgrade" : "Switch"} to ${change.plan.tier}?` : ""}
      body={
        change ? (
          <div className="space-y-3">
            <Row label="new plan">
              <span className="text-[12px] text-[var(--color-text)]">{change.plan.tier}</span>
            </Row>
            <Row label="price">
              <span className="text-[12px] text-[var(--color-text)] font-mono tabular-nums">
                {formatPrice(change.price.amount, change.price.currency)}/
                {change.price.interval === "year" ? "yr" : "mo"}
              </span>
            </Row>
            <ProrationBody change={change} />
          </div>
        ) : undefined
      }
      confirmLabel={
        change?.loadingPreview ? "calculating..." : change?.isUpgrade ? "upgrade now" : "confirm change"
      }
      cancelLabel="cancel"
      variant="default"
      onConfirm={() => {
        if (change && !change.loadingPreview) onConfirm(change.priceId);
      }}
      onCancel={onCancel}
    />
  );
}
