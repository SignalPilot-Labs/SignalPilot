"use client";

import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import {
  CreditCard,
  CheckCircle2,
  XCircle,
  Info,
  Loader2,
  AlertTriangle,
  Zap,
  Users,
  ArrowRight,
  ExternalLink,
  Building2,
  Mail,
} from "lucide-react";
import { useAppAuth } from "@/lib/auth-context";
import { useBackendClient } from "@/lib/backend-client";
import type { PlanInfo, PlanPrice } from "@/lib/backend-client";
import { useSubscription } from "@/lib/subscription-context";
import { usePlan } from "@/lib/hooks/use-gateway-data";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/data-viz";
import { SectionHeader } from "@/components/ui/section-header";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { BillingSkeleton } from "@/components/ui/skeleton";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatPrice(amount: number, currency: string): string {
  const dollars = amount / 100;
  const hasCents = dollars % 1 !== 0;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: hasCents ? 2 : 0,
    maximumFractionDigits: hasCents ? 2 : 0,
  }).format(dollars);
}

function getMonthlyEquivalent(price: PlanPrice): number {
  if (price.interval === "year") return Math.round(price.amount / 12);
  return price.amount;
}

const HIGHLIGHT_COLORS: Record<string, string> = {
  success: "var(--color-success)",
  warning: "var(--color-warning)",
  default: "var(--color-text-muted)",
};

// ---------------------------------------------------------------------------
// Tier badge
// ---------------------------------------------------------------------------

function TierBadge({ tier }: { tier: string }) {
  const colorMap: Record<string, string> = {
    free: "text-[var(--color-text-dim)] border-[var(--color-border)]",
    pro: "text-[var(--color-success)] border-[var(--color-success)]/40",
    team: "text-[var(--color-warning)] border-[var(--color-warning)]/40",
  };
  const classes = colorMap[tier] ?? colorMap.free;
  return (
    <span
      className={`px-2 py-0.5 text-[11px] border tracking-[0.15em] uppercase ${classes}`}
    >
      {tier}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Billing interval toggle
// ---------------------------------------------------------------------------

function IntervalToggle({
  interval,
  onChange,
}: {
  interval: "month" | "year";
  onChange: (v: "month" | "year") => void;
}) {
  return (
    <div className="flex items-center gap-2 mb-5">
      <button
        onClick={() => onChange("month")}
        className={`px-3 py-1.5 text-[11px] tracking-[0.15em] uppercase border transition-all ${
          interval === "month"
            ? "border-[var(--color-text-muted)] text-[var(--color-text)]"
            : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
        }`}
      >
        monthly
      </button>
      <button
        onClick={() => onChange("year")}
        className={`px-3 py-1.5 text-[11px] tracking-[0.15em] uppercase border transition-all ${
          interval === "year"
            ? "border-[var(--color-text-muted)] text-[var(--color-text)]"
            : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
        }`}
      >
        annual
        <span className="ml-1.5 text-[var(--color-success)]">save ~30%</span>
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Plan card — fully dynamic from Stripe data
// ---------------------------------------------------------------------------

const TIER_ORDER: Record<string, number> = { free: 0, pro: 1, team: 2, enterprise: 3 };

function PlanCard({
  plan,
  interval,
  currentTier,
  onUpgrade,
  upgrading,
}: {
  plan: PlanInfo;
  interval: "month" | "year";
  currentTier: string;
  onUpgrade: (priceId: string) => void;
  upgrading: string | null;
}) {
  const highlightColor = HIGHLIGHT_COLORS[plan.highlight_color] ?? HIGHLIGHT_COLORS.default;
  const price = plan.prices.find((p) => p.interval === interval);
  const monthlyPrice = plan.prices.find((p) => p.interval === "month");
  const Icon = plan.tier === "pro" ? Zap : Users;

  if (!price) return null;

  const isUpgrading = upgrading === price.price_id;
  const isCurrent = plan.tier === currentTier;
  const isHigher = (TIER_ORDER[plan.tier] ?? 0) > (TIER_ORDER[currentTier] ?? 0);
  const isLower = (TIER_ORDER[plan.tier] ?? 0) < (TIER_ORDER[currentTier] ?? 0);
  const displayAmount = formatPrice(price.amount, price.currency);
  const monthlyEquiv = getMonthlyEquivalent(price);
  const showSavings = interval === "year" && monthlyPrice && monthlyEquiv < monthlyPrice.amount;

  return (
    <div
      className="flex-1 border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 hover:border-[var(--color-border-hover)] transition-all"
      style={{ borderTopColor: highlightColor, borderTopWidth: "2px" }}
    >
      {/* Plan header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon
            className="w-3.5 h-3.5"
            style={{ color: highlightColor }}
            strokeWidth={1.5}
          />
          <span className="text-[12px] uppercase tracking-[0.15em] text-[var(--color-text-muted)]">
            {plan.tier}
          </span>
        </div>
        <div className="text-right">
          <div className="flex items-baseline gap-0.5">
            <span
              className="text-xl font-bold tracking-tight"
              style={{ color: highlightColor }}
            >
              {interval === "year"
                ? formatPrice(monthlyEquiv, price.currency)
                : displayAmount}
            </span>
            <span className="text-[12px] text-[var(--color-text-dim)]">
              /mo
            </span>
          </div>
          {interval === "year" && (
            <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider">
              {displayAmount}/yr
            </span>
          )}
          {showSavings && (
            <span className="block text-[11px] text-[var(--color-success)] tracking-wider">
              save {formatPrice(monthlyPrice.amount * 12 - price.amount, price.currency)}/yr
            </span>
          )}
        </div>
      </div>

      <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed mb-4">
        {plan.description}
      </p>

      {/* Features list */}
      <ul className="space-y-2 mb-5">
        {plan.features.map((f) => (
          <li key={f} className="flex items-center gap-2">
            <CheckCircle2
              className="w-3 h-3 flex-shrink-0"
              style={{ color: highlightColor }}
              strokeWidth={1.5}
            />
            <span className="text-[12px] text-[var(--color-text-muted)] tracking-wider">
              {f}
            </span>
          </li>
        ))}
      </ul>

      {/* Action button */}
      {isCurrent ? (
        <div
          className="w-full flex items-center justify-center gap-2 px-4 py-2 text-[12px] tracking-wider uppercase border"
          style={{
            borderColor: highlightColor,
            color: highlightColor,
            opacity: 0.7,
          }}
        >
          <CheckCircle2 className="w-3 h-3" />
          current plan
        </div>
      ) : (
        <button
          onClick={() => onUpgrade(price.price_id)}
          disabled={isUpgrading || upgrading !== null}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 text-[12px] tracking-wider uppercase border transition-all disabled:opacity-40 hover:bg-[var(--color-bg-hover)]"
          style={{
            borderColor: highlightColor,
            color: highlightColor,
          }}
        >
          {isUpgrading ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <ArrowRight className="w-3 h-3" />
          )}
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
          title="billing"
          subtitle="subscription"
          description="manage your signalpilot subscription and billing"
        />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          <div className="p-6 flex items-start gap-3">
            <Info
              className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0"
              strokeWidth={1.5}
            />
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
              billing is available in cloud mode. local deployments have full
              team-tier access at no cost. set{" "}
              <code className="text-[var(--color-text-muted)]">
                NEXT_PUBLIC_DEPLOYMENT_MODE=cloud
              </code>{" "}
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
  const { status, isLoaded, refetch } = useSubscription();
  const { data: plan, mutate: mutatePlan } = usePlan();
  const planTier = plan?.tier ?? "free";
  const maxApiKeys = plan?.limits.api_keys === "unlimited" ? "∞" : (plan?.limits.api_keys ?? 1);
  const searchParams = useSearchParams();
  const { toast } = useToast();

  const [upgrading, setUpgrading] = useState<string | null>(null);
  const [managingPortal, setManagingPortal] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [billingInterval, setBillingInterval] = useState<"month" | "year">("month");
  const [plans, setPlans] = useState<PlanInfo[] | null>(null);
  const [plansError, setPlansError] = useState(false);
  const [pendingChange, setPendingChange] = useState<{
    priceId: string;
    plan: PlanInfo;
    price: PlanPrice;
    isUpgrade: boolean;
    proration: { amount_due: number; currency: string; credit: number; new_charge: number; immediate: boolean; effective_date: string | null } | null;
    loadingPreview: boolean;
  } | null>(null);

  // Fetch plans from backend (which fetches from Stripe)
  useEffect(() => {
    let cancelled = false;
    client
      .getPlans()
      .then((res) => {
        if (!cancelled) {
          // Sort so pro comes before team
          const sorted = [...res.plans].sort((a, b) => {
            const order: Record<string, number> = { pro: 0, team: 1 };
            return (order[a.tier] ?? 99) - (order[b.tier] ?? 99);
          });
          setPlans(sorted);
        }
      })
      .catch(() => {
        if (!cancelled) setPlansError(true);
      });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Determine checkout outcome from URL params
  const checkoutOutcome = searchParams.get("checkout");

  // Refetch subscription + plan after successful checkout return
  useEffect(() => {
    if (checkoutOutcome === "success") {
      refetch();
      mutatePlan();
    }
  }, [checkoutOutcome, refetch, mutatePlan]);

  const executeCheckout = useCallback(
    async (priceId: string) => {
      setActionError(null);
      setUpgrading(priceId);
      try {
        const origin = window.location.origin;
        const successUrl = `${origin}/settings/billing?checkout=success`;
        const cancelUrl = `${origin}/settings/billing?checkout=canceled`;
        const res = await client.createCheckoutSession(
          priceId,
          successUrl,
          cancelUrl,
        );
        if (res.action === "updated") {
          toast("plan updated successfully", "success");
          refetch();
          mutatePlan();
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
    [client, toast, refetch, mutatePlan],
  );

  const handleUpgrade = useCallback(
    async (priceId: string) => {
      const targetPlan = plans?.find((p) => p.prices.some((pr) => pr.price_id === priceId));
      const targetPrice = targetPlan?.prices.find((pr) => pr.price_id === priceId);

      // For paid → paid, fetch proration preview then show confirmation
      if (planTier !== "free" && targetPlan && targetPrice) {
        const isUpgrade = (TIER_ORDER[targetPlan.tier] ?? 0) > (TIER_ORDER[planTier] ?? 0);
        setPendingChange({ priceId, plan: targetPlan, price: targetPrice, isUpgrade, proration: null, loadingPreview: true });

        try {
          const preview = await client.previewProration(priceId);
          setPendingChange((prev) => prev ? { ...prev, proration: preview, loadingPreview: false } : null);
        } catch {
          setPendingChange((prev) => prev ? { ...prev, loadingPreview: false } : null);
        }
        return;
      }

      // Free → paid: go straight to Stripe checkout
      executeCheckout(priceId);
    },
    [plans, planTier, executeCheckout, client],
  );

  const handleManagePortal = useCallback(async () => {
    setActionError(null);
    setManagingPortal(true);
    try {
      const returnUrl = `${window.location.origin}/settings/billing`;
      const { portal_url } = await client.createPortalSession(returnUrl);
      window.location.href = portal_url;
    } catch (e) {
      setActionError(String(e));
      toast("failed to open billing portal", "error");
      setManagingPortal(false);
    }
  }, [client, toast]);

  // ---------------------------------------------------------------------------
  // Loading
  // ---------------------------------------------------------------------------

  if (!isLoaded) {
    return <BillingSkeleton />;
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const isFreeTier = planTier === "free";

  const statusLabel = status === "active"
    ? "active"
    : status === "past_due"
      ? "past due"
      : status === "canceled"
        ? "canceled"
        : status;

  return (
    <div className="p-8 max-w-5xl animate-fade-in">
      <PageHeader
        title="billing"
        subtitle="subscription"
        description="manage your signalpilot subscription and billing"
      />

      <TerminalBar
        path="settings/billing --status"
        status={
          <StatusDot
            status={
              status === "active"
                ? "healthy"
                : status === "past_due"
                  ? "warning"
                  : "error"
            }
            size={4}
          />
        }
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            plan:{" "}
            <code className="text-[12px] text-[var(--color-text)]">
              {planTier}
            </code>
          </span>
          <span className="text-[var(--color-text-dim)]">
            keys:{" "}
            <code className="text-[12px] text-[var(--color-text)]">
              {maxApiKeys}
            </code>
          </span>
        </div>
      </TerminalBar>

      {/* Checkout outcome banners */}
      {checkoutOutcome === "success" && (
        <div className="mb-6 flex items-start gap-3 p-4 border border-[var(--color-success)]/30 bg-[var(--color-success)]/5 animate-fade-in">
          <CheckCircle2
            className="w-4 h-4 text-[var(--color-success)] mt-0.5 flex-shrink-0"
            strokeWidth={1.5}
          />
          <div>
            <p className="text-[12px] text-[var(--color-success)] tracking-wider font-medium">
              subscription activated
            </p>
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider mt-0.5">
              your plan has been upgraded. it may take a moment to reflect below.
            </p>
          </div>
        </div>
      )}

      {checkoutOutcome === "canceled" && (
        <div className="mb-6 flex items-start gap-3 p-4 border border-[var(--color-border)] bg-[var(--color-bg-card)] animate-fade-in">
          <XCircle
            className="w-4 h-4 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0"
            strokeWidth={1.5}
          />
          <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
            checkout was canceled. no changes were made to your subscription.
          </p>
        </div>
      )}

      {/* Error banner */}
      {actionError && (
        <div className="mb-6 flex items-start gap-2 p-3 border border-[var(--color-error)]/20 bg-[var(--color-error)]/5 animate-fade-in">
          <AlertTriangle
            className="w-3.5 h-3.5 text-[var(--color-error)] mt-0.5 flex-shrink-0"
            strokeWidth={1.5}
          />
          <p className="text-[12px] text-[var(--color-error)] tracking-wider">
            {actionError}
          </p>
        </div>
      )}

      {/* Current plan section */}
      <section className="mb-8">
        <SectionHeader icon={CreditCard} title="current plan" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <TierBadge tier={planTier} />
              <div>
                <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
                  status:{" "}
                  <span
                    className={
                      status === "active"
                        ? "text-[var(--color-success)]"
                        : status === "past_due"
                          ? "text-[var(--color-warning)]"
                          : "text-[var(--color-error)]"
                    }
                  >
                    {statusLabel}
                  </span>
                </span>
                <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider mt-0.5">
                  {maxApiKeys} api keys allowed
                </p>
              </div>
            </div>
            {/* Manage subscription button — only for paid tiers */}
            {!isFreeTier && (
              <button
                onClick={handleManagePortal}
                disabled={managingPortal}
                className="flex items-center gap-2 px-4 py-2 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase disabled:opacity-40"
              >
                {managingPortal ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <ExternalLink className="w-3 h-3" />
                )}
                {managingPortal ? "redirecting..." : "manage subscription"}
              </button>
            )}
          </div>
        </div>
      </section>

      {/* Plans section — always shown */}
      <section className="mb-8">
        <SectionHeader icon={Zap} title="plans" />

        {plans === null && !plansError && (
          <div className="flex items-center gap-2 p-5 border border-[var(--color-border)] bg-[var(--color-bg-card)]">
            <Loader2 className="w-3.5 h-3.5 text-[var(--color-text-dim)] animate-spin" />
            <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
              loading plans...
            </span>
          </div>
        )}

        {plansError && (
          <div className="flex items-start gap-3 p-5 border border-[var(--color-border)] bg-[var(--color-bg-card)]">
            <AlertTriangle className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
              unable to load pricing. please try again later.
            </p>
          </div>
        )}

        {plans && plans.length > 0 && (
          <>
            <IntervalToggle interval={billingInterval} onChange={setBillingInterval} />
            <div className="flex gap-4">
              {plans.map((p) => (
                <PlanCard
                  key={p.tier}
                  plan={p}
                  interval={billingInterval}
                  currentTier={planTier}
                  onUpgrade={handleUpgrade}
                  upgrading={upgrading}
                />
              ))}

              {/* Enterprise card — static, contact us */}
              <div
                className="flex-1 border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 hover:border-[var(--color-border-hover)] transition-all"
                style={{ borderTopColor: "var(--color-text-muted)", borderTopWidth: "2px" }}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <Building2
                      className="w-3.5 h-3.5 text-[var(--color-text-muted)]"
                      strokeWidth={1.5}
                    />
                    <span className="text-[12px] uppercase tracking-[0.15em] text-[var(--color-text-muted)]">
                      enterprise
                    </span>
                  </div>
                  <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider italic">
                    contact us
                  </span>
                </div>

                <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed mb-4">
                  for large organizations with dedicated infrastructure and compliance needs
                </p>

                <ul className="space-y-2 mb-5">
                  {[
                    "dedicated infrastructure",
                    "custom sla (99.9%+)",
                    "on-prem / vpc deployment",
                    "custom pii rules",
                    "soc 2 compliance path",
                    "dedicated slack channel",
                    "quarterly business reviews",
                  ].map((f) => (
                    <li key={f} className="flex items-center gap-2">
                      <CheckCircle2
                        className="w-3 h-3 flex-shrink-0 text-[var(--color-text-muted)]"
                        strokeWidth={1.5}
                      />
                      <span className="text-[12px] text-[var(--color-text-muted)] tracking-wider">
                        {f}
                      </span>
                    </li>
                  ))}
                </ul>

                {planTier === "enterprise" ? (
                  <div
                    className="w-full flex items-center justify-center gap-2 px-4 py-2 text-[12px] tracking-wider uppercase border"
                    style={{ borderColor: "var(--color-text-muted)", color: "var(--color-text-muted)", opacity: 0.7 }}
                  >
                    <CheckCircle2 className="w-3 h-3" />
                    current plan
                  </div>
                ) : (
                  <a
                    href="mailto:daniel@signalpilot.ai?subject=SignalPilot%20Enterprise"
                    className="w-full flex items-center justify-center gap-2 px-4 py-2 text-[12px] tracking-wider uppercase border border-[var(--color-text-muted)] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] transition-all"
                  >
                    <Mail className="w-3 h-3" />
                    contact us
                  </a>
                )}
              </div>
            </div>
            <p className="mt-3 text-[11px] text-[var(--color-text-dim)] tracking-wider">
              cancel anytime. prices in usd. self-hosted is always free.
            </p>
          </>
        )}
      </section>

      {/* Plan change confirmation dialog */}
      <ConfirmDialog
        open={pendingChange !== null}
        title={pendingChange?.isUpgrade ? "upgrade plan" : "change plan"}
        message={
          pendingChange
            ? `${pendingChange.isUpgrade ? "Upgrade" : "Switch"} to ${pendingChange.plan.tier}?`
            : ""
        }
        body={
          pendingChange ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between py-2 border-b border-[var(--color-border)]">
                <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                  new plan
                </span>
                <span className="text-[12px] text-[var(--color-text)] tracking-wider">
                  {pendingChange.plan.tier}
                </span>
              </div>
              <div className="flex items-center justify-between py-2 border-b border-[var(--color-border)]">
                <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                  price
                </span>
                <span className="text-[12px] text-[var(--color-text)] tracking-wider tabular-nums">
                  {formatPrice(pendingChange.price.amount, pendingChange.price.currency)}
                  /{pendingChange.price.interval === "year" ? "yr" : "mo"}
                </span>
              </div>

              {pendingChange.loadingPreview ? (
                <div className="flex items-center gap-2 py-2">
                  <Loader2 className="w-3 h-3 text-[var(--color-text-dim)] animate-spin" />
                  <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider">
                    calculating...
                  </span>
                </div>
              ) : pendingChange.proration ? (
                pendingChange.proration.immediate ? (
                  <>
                    {pendingChange.proration.credit > 0 && (
                      <div className="flex items-center justify-between py-2 border-b border-[var(--color-border)]">
                        <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                          credit from current plan
                        </span>
                        <span className="text-[12px] text-[var(--color-success)] tracking-wider tabular-nums">
                          −{formatPrice(pendingChange.proration.credit, pendingChange.proration.currency)}
                        </span>
                      </div>
                    )}
                    <div className="flex items-center justify-between py-2 border-b border-[var(--color-border)]">
                      <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                        charge today
                      </span>
                      <span className="text-[13px] font-medium tracking-wider tabular-nums text-[var(--color-text)]">
                        {formatPrice(pendingChange.proration.amount_due, pendingChange.proration.currency)}
                      </span>
                    </div>
                  </>
                ) : (
                  <div className="py-2 space-y-2">
                    <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
                      your current plan stays active until the end of this billing period.
                      no charge today.
                    </p>
                    {pendingChange.proration.effective_date && (
                      <p className="text-[11px] text-[var(--color-error)] tracking-wider leading-relaxed">
                        your plan will change to {pendingChange.plan.tier} on{" "}
                        {new Date(pendingChange.proration.effective_date + "T00:00:00").toLocaleDateString("en-US", {
                          month: "long",
                          day: "numeric",
                          year: "numeric",
                        })}
                      </p>
                    )}
                  </div>
                )
              ) : (
                <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
                  the prorated difference will be charged immediately.
                </p>
              )}
            </div>
          ) : undefined
        }
        confirmLabel={pendingChange?.loadingPreview ? "calculating..." : pendingChange?.isUpgrade ? "upgrade now" : "confirm change"}
        cancelLabel="cancel"
        variant="default"
        onConfirm={() => {
          if (pendingChange && !pendingChange.loadingPreview) {
            executeCheckout(pendingChange.priceId);
            setPendingChange(null);
          }
        }}
        onCancel={() => setPendingChange(null)}
      />
    </div>
  );
}
