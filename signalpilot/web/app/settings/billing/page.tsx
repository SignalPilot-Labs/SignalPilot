"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  Coins,
  CreditCard,
  ExternalLink,
  Info,
  Loader2,
  XCircle,
  Zap,
} from "lucide-react";
import { useAppAuth } from "~/lib/auth-context";
import { useBackendClient } from "~/lib/backend-client";
import type { PlanInfo, RateCard } from "~/lib/backend-client";
import { useSubscription } from "~/lib/subscription-context";
import { TIER_RANK, tierLabel, type EntitlementTier } from "~/lib/entitlement";
import { formatCredits } from "~/lib/billing-rates";
import { PageHeader, TerminalBar } from "~/components/ui/page-header";
import { StatusDot } from "~/components/ui/data-viz";
import { SectionHeader } from "~/components/ui/section-header";
import { useToast } from "~/components/ui/toast";
import { ConfirmDialog } from "~/components/ui/confirm-dialog";
import { BillingSkeleton } from "~/components/ui/skeleton";
import { TierBadge } from "~/components/branding/tier-badge";
import { TierAccent } from "~/components/branding/tier-accent";
import { IntervalToggle, PlanCard } from "~/components/billing/plan-card";
import { EnterpriseCard, EnterpriseContractSummary } from "~/components/billing/enterprise-card";
import { CreditRateTable } from "~/components/billing/credit-rate-table";
import { PlanChangeDialog, type PendingPlanChange } from "~/components/billing/plan-change-dialog";

const PLAN_ORDER: Record<string, number> = { team: 0, scale: 1, enterprise: 2 };

function rank(tier: string): number {
  return TIER_RANK[tier as EntitlementTier] ?? 0;
}

// ---------------------------------------------------------------------------
// Main gate — checks isCloudMode and auth state before rendering content
// ---------------------------------------------------------------------------

export default function BillingPage() {
  const { isCloudMode, isLoaded } = useAppAuth();

  if (!isLoaded) {
    return <BillingSkeleton />;
  }

  if (!isCloudMode) {
    return (
      <div className="p-8 max-w-5xl animate-fade-in">
        <PageHeader
          title="plans"
          subtitle="subscription"
          description="manage your signalpilot plan and subscription"
        />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px]">
          <div className="p-6 flex items-start gap-3">
            <Info className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
            <p className="text-[12px] text-[var(--color-text-dim)] leading-relaxed">
              billing is available in cloud mode. local deployments are unlimited at no cost. set{" "}
              <code className="text-[var(--color-text-muted)]">NEXT_PUBLIC_DEPLOYMENT_MODE=cloud</code>{" "}
              and configure clerk to manage subscriptions.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return <BillingContent />;
}

// ---------------------------------------------------------------------------
// Content component — safe to call hooks (ClerkProvider is present)
// ---------------------------------------------------------------------------

function BillingContent() {
  const client = useBackendClient();
  const subscription = useSubscription();
  const {
    tier,
    isBillable,
    status,
    isLoaded,
    refetch,
    pendingDowngradeTo,
    pendingDowngradeDate,
    cancelAtPeriodEnd,
    cancelDate,
    entitlement,
    contract,
    currentPeriodEnd,
  } = subscription;
  const searchParams = useSearchParams();
  const { toast } = useToast();

  const [upgrading, setUpgrading] = useState<string | null>(null);
  const [managingPortal, setManagingPortal] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [billingInterval, setBillingInterval] = useState<"month" | "year">(
    entitlement.billingInterval,
  );
  const [plans, setPlans] = useState<PlanInfo[] | null>(null);
  /** The live rate card; the rate table falls back to the local constants until it arrives. */
  const [rates, setRates] = useState<RateCard | null>(null);
  const [plansError, setPlansError] = useState(false);
  const [cancelConfirmOpen, setCancelConfirmOpen] = useState(false);
  const [canceling, setCanceling] = useState(false);
  const [pendingChange, setPendingChange] = useState<PendingPlanChange | null>(null);

  // Fetch plans from the backend (Stripe products plus the static allowance table)
  useEffect(() => {
    let cancelled = false;
    client
      .getPlans()
      .then((res) => {
        if (cancelled) return;
        const sorted = [...res.plans].sort(
          (a, b) => (PLAN_ORDER[a.tier] ?? 99) - (PLAN_ORDER[b.tier] ?? 99),
        );
        setPlans(sorted);
        setRates(res.rates);
      })
      .catch(() => {
        if (!cancelled) setPlansError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const checkoutOutcome = searchParams.get("checkout");

  useEffect(() => {
    // Back from Stripe Checkout: re-read the row and make the gateway drop
    // its cached (free) entitlement so gated pages open right away.
    if (checkoutOutcome === "success") refetch({ refresh: true });
  }, [checkoutOutcome, refetch]);

  const executeCheckout = useCallback(
    async (priceId: string) => {
      setActionError(null);
      setUpgrading(priceId);
      try {
        const origin = window.location.origin;
        const res = await client.createCheckoutSession(
          priceId,
          `${origin}/settings/billing?checkout=success`,
          `${origin}/settings/billing?checkout=canceled`,
        );
        if (res.action === "updated") {
          toast("plan updated successfully", "success");
          refetch();
          setUpgrading(null);
        } else if (res.checkout_url) {
          window.location.href = res.checkout_url;
        }
      } catch (e) {
        setActionError(String(e));
        toast("failed to change plan", "error");
        setUpgrading(null);
      }
    },
    [client, toast, refetch],
  );

  const handleUpgrade = useCallback(
    async (priceId: string) => {
      const targetPlan = plans?.find((p) => p.prices.some((pr) => pr.price_id === priceId));
      const targetPrice = targetPlan?.prices.find((pr) => pr.price_id === priceId);

      // Paid to paid: fetch the proration preview, then confirm
      if (isBillable && tier !== "free" && targetPlan && targetPrice) {
        const isUpgrade = rank(targetPlan.tier) > rank(tier);
        setPendingChange({ priceId, plan: targetPlan, price: targetPrice, isUpgrade, proration: null, loadingPreview: true });
        try {
          const preview = await client.previewProration(priceId);
          setPendingChange((prev) => (prev ? { ...prev, proration: preview, loadingPreview: false } : null));
        } catch {
          setPendingChange((prev) => (prev ? { ...prev, loadingPreview: false } : null));
        }
        return;
      }

      // Free to paid: straight to Stripe checkout
      executeCheckout(priceId);
    },
    [plans, tier, isBillable, executeCheckout, client],
  );

  const handleManagePortal = useCallback(async () => {
    setActionError(null);
    setManagingPortal(true);
    try {
      const { portal_url } = await client.createPortalSession(`${window.location.origin}/settings/billing`);
      window.location.href = portal_url;
    } catch (e) {
      setActionError(String(e));
      toast("failed to open billing portal", "error");
      setManagingPortal(false);
    }
  }, [client, toast]);

  const handleCancel = useCallback(async () => {
    setCancelConfirmOpen(false);
    setCanceling(true);
    setActionError(null);
    try {
      await client.cancelSubscription();
      toast("subscription will cancel at end of billing period", "success");
      refetch();
    } catch (e) {
      setActionError(String(e));
      toast("failed to cancel subscription", "error");
    } finally {
      setCanceling(false);
    }
  }, [client, toast, refetch]);

  const handleReactivate = useCallback(async () => {
    setActionError(null);
    try {
      await client.reactivateSubscription();
      toast("subscription reactivated", "success");
      refetch();
    } catch (e) {
      setActionError(String(e));
      toast("failed to reactivate subscription", "error");
    }
  }, [client, toast, refetch]);

  if (!isLoaded) {
    return <BillingSkeleton />;
  }

  const isFreeTier = tier === "free";
  const isEnterprise = tier === "enterprise";
  const statusLabel = status === "past_due" ? "past due" : status;
  const statusTone = status === "active" || status === "trialing" ? "healthy" : status === "past_due" ? "warning" : "error";
  const statusClass =
    statusTone === "healthy"
      ? "text-[var(--color-success)]"
      : statusTone === "warning"
        ? "text-[var(--color-warning)]"
        : "text-[var(--color-error)]";
  const selfServePlans = plans?.filter((p) => p.tier !== "enterprise") ?? [];
  const enterprisePlan = plans?.find((p) => p.tier === "enterprise") ?? null;

  return (
    <div className="p-8 max-w-5xl animate-fade-in">
      <PageHeader
        title="billing"
        subtitle="subscription"
        description="one flat fee per plan, allowances included, everything beyond in credits"
      />

      <TerminalBar path="settings/plans --status" status={<StatusDot status={statusTone} size={4} />}>
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            plan: <code className="text-[12px] text-[var(--color-text)]">{tier}</code>
          </span>
          <span className="text-[var(--color-text-dim)]">
            credits/month:{" "}
            <code className="text-[12px] text-[var(--color-text)]">{formatCredits(entitlement.includedCredits)}</code>
          </span>
          <span className="text-[var(--color-text-dim)]">
            billed: <code className="text-[12px] text-[var(--color-text)]">{entitlement.billingInterval === "year" ? "annually" : "monthly"}</code>
          </span>
        </div>
      </TerminalBar>

      {checkoutOutcome === "success" && (
        <div className="mb-6 flex items-start gap-3 p-4 border border-[var(--color-success)]/30 bg-[var(--color-success)]/5 rounded-[10px] animate-fade-in">
          <CheckCircle2 className="w-4 h-4 text-[var(--color-success)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
          <div>
            <p className="text-[12px] text-[var(--color-success)] font-medium">subscription activated</p>
            <p className="text-[12px] text-[var(--color-text-dim)] mt-0.5">
              your plan has been updated. it may take a moment to reflect below.
            </p>
          </div>
        </div>
      )}

      {checkoutOutcome === "canceled" && (
        <div className="mb-6 flex items-start gap-3 p-4 border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[10px] animate-fade-in">
          <XCircle className="w-4 h-4 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
          <p className="text-[12px] text-[var(--color-text-dim)]">
            checkout was canceled. no changes were made to your subscription.
          </p>
        </div>
      )}

      {actionError && (
        <div className="mb-6 flex items-start gap-2 p-3 border border-[var(--color-error)]/20 bg-[var(--color-error)]/5 rounded-[10px] animate-fade-in">
          <AlertTriangle className="w-3.5 h-3.5 text-[var(--color-error)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
          <p className="text-[12px] text-[var(--color-error)]">{actionError}</p>
        </div>
      )}

      {/* Current plan */}
      <section className="mb-8">
        <SectionHeader icon={CreditCard} title="current plan" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              {isBillable ? (
                <TierBadge />
              ) : (
                <span className="inline-flex items-center gap-1.5">
                  <span className="inline-block w-[5px] h-[5px] flex-shrink-0 rounded-full bg-[var(--color-text-dim)]" aria-hidden="true" />
                  <span className="text-[11px] leading-none tracking-[0.08em] uppercase text-[var(--color-text-dim)]">
                    {tierLabel(tier)}
                  </span>
                </span>
              )}
              <div>
                <span className="text-[12px] text-[var(--color-text-dim)]">
                  status: <span className={statusClass}>{statusLabel}</span>
                </span>
                <p className="text-[12px] text-[var(--color-text-dim)] mt-0.5">
                  {isFreeTier
                    ? "every feature is visible; choose a plan to start running work"
                    : `${entitlement.includedSeats.toLocaleString()} seats · ${entitlement.includedModels.toLocaleString()} covered models · ${entitlement.includedEvalRuns.toLocaleString()} eval runs · ${formatCredits(entitlement.includedCredits)} credits per month${entitlement.managed ? " · managed" : ""}`}
                </p>
              </div>
            </div>
            {!isFreeTier && (
              <button
                onClick={handleManagePortal}
                disabled={managingPortal}
                className="flex items-center gap-2 px-4 py-2 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-colors duration-150 disabled:opacity-40"
              >
                {managingPortal ? <Loader2 className="w-3 h-3 animate-spin" /> : <ExternalLink className="w-3 h-3" />}
                {managingPortal ? "redirecting..." : "manage subscription"}
              </button>
            )}
          </div>
        </div>
        <TierAccent />
      </section>

      {isEnterprise && (
        <section className="mb-8">
          <SectionHeader icon={Building2} title="contract" />
          <EnterpriseContractSummary entitlement={entitlement} contract={contract} currentPeriodEnd={currentPeriodEnd} />
        </section>
      )}

      {pendingDowngradeTo && pendingDowngradeDate && (
        <div className="mb-6 flex items-start gap-3 p-4 border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 rounded-[10px] animate-fade-in">
          <AlertTriangle className="w-4 h-4 text-[var(--color-warning)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
          <div>
            <p className="text-[12px] text-[var(--color-warning)] font-medium">plan change scheduled</p>
            <p className="text-[12px] text-[var(--color-text-dim)] mt-0.5">
              your plan will change to <span className="text-[var(--color-text-muted)]">{pendingDowngradeTo}</span> on{" "}
              <span className="text-[var(--color-text-muted)] tabular-nums">
                {new Date(pendingDowngradeDate + "T00:00:00").toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
              </span>
              . you keep full {tier} access until then.
            </p>
          </div>
        </div>
      )}

      {/* Plans */}
      <section className="mb-8">
        <SectionHeader icon={Zap} title="plans" />

        {plans === null && !plansError && (
          <div className="flex items-center gap-2 p-5 border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px]">
            <Loader2 className="w-3.5 h-3.5 text-[var(--color-text-dim)] animate-spin" />
            <span className="text-[12px] text-[var(--color-text-dim)]">loading plans...</span>
          </div>
        )}

        {plansError && (
          <div className="flex items-start gap-3 p-5 border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px]">
            <AlertTriangle className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
            <p className="text-[12px] text-[var(--color-text-dim)]">unable to load pricing. please try again later.</p>
          </div>
        )}

        {plans && (
          <>
            <IntervalToggle interval={billingInterval} onChange={setBillingInterval} />
            <div className="flex flex-col md:flex-row gap-4">
              {selfServePlans.map((p) => (
                <PlanCard
                  key={p.tier}
                  plan={p}
                  interval={billingInterval}
                  currentTier={tier}
                  pendingDowngradeTo={pendingDowngradeTo}
                  pendingDowngradeDate={pendingDowngradeDate}
                  onUpgrade={handleUpgrade}
                  upgrading={upgrading}
                />
              ))}
              <EnterpriseCard plan={enterprisePlan} isCurrent={isEnterprise} />
            </div>
            <p className="mt-3 text-[11px] text-[var(--color-text-dim)]">
              annual plans bill the flat fee yearly; credits are granted and settled monthly. month-to-month is 25% more.
              cancel anytime. prices in usd. self-hosted is always free.
            </p>
          </>
        )}
      </section>

      {/* Credit rates */}
      <section className="mb-8">
        <SectionHeader icon={Coins} title="credit rates" />
        <CreditRateTable enterprise={isEnterprise} rates={rates} />
      </section>

      {/* Cancel / reactivate */}
      {!isFreeTier && !isEnterprise && (
        <section className="mb-8">
          <SectionHeader icon={AlertTriangle} title="cancel subscription" iconColor="text-[var(--color-error)]" />
          <div className="border border-[var(--color-error)]/30 bg-[var(--color-bg-card)] rounded-[14px] p-5">
            {cancelAtPeriodEnd ? (
              <div className="space-y-3">
                <p className="text-[12px] text-[var(--color-text-dim)] leading-relaxed">
                  your subscription is set to cancel
                  {cancelDate && (
                    <>
                      {" "}on{" "}
                      <span className="text-[var(--color-error)] tabular-nums">
                        {new Date(cancelDate + "T00:00:00").toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
                      </span>
                    </>
                  )}
                  . you keep full access until then.
                </p>
                <button
                  onClick={handleReactivate}
                  className="flex items-center gap-2 px-4 py-2 text-[12px] text-[var(--color-success)] border border-[var(--color-success)]/40 rounded-[10px] hover:bg-[var(--color-bg-hover)] transition-colors duration-150"
                >
                  <CheckCircle2 className="w-3 h-3" />
                  keep subscription
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-[12px] text-[var(--color-text-dim)] leading-relaxed">
                  cancel your subscription. you keep full access until the end of the current billing period, then
                  revert to the free plan: every feature stays visible, nothing runs.
                </p>
                <button
                  onClick={() => setCancelConfirmOpen(true)}
                  disabled={canceling}
                  className="flex items-center gap-2 px-4 py-2 text-[12px] text-[var(--color-error)] border border-[var(--color-error)]/40 rounded-[10px] hover:bg-[var(--color-error)]/5 transition-colors duration-150 disabled:opacity-40"
                >
                  {canceling ? <Loader2 className="w-3 h-3 animate-spin" /> : <XCircle className="w-3 h-3" />}
                  {canceling ? "canceling..." : "cancel subscription"}
                </button>
              </div>
            )}
          </div>
        </section>
      )}

      <ConfirmDialog
        open={cancelConfirmOpen}
        title="cancel subscription"
        message="Are you sure you want to cancel?"
        body={
          <p className="text-[11px] text-[var(--color-text-dim)] leading-relaxed">
            your {tier} plan stays active until the end of the current billing period. after that, your account
            reverts to the free plan and nothing runs until you choose a plan again.
          </p>
        }
        confirmLabel="cancel subscription"
        cancelLabel="keep subscription"
        variant="danger"
        onConfirm={handleCancel}
        onCancel={() => setCancelConfirmOpen(false)}
      />

      <PlanChangeDialog
        change={pendingChange}
        onConfirm={(priceId) => {
          executeCheckout(priceId);
          setPendingChange(null);
        }}
        onCancel={() => setPendingChange(null)}
      />
    </div>
  );
}
