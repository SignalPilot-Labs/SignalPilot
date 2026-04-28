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
} from "lucide-react";
import { useAppAuth } from "@/lib/auth-context";
import { useBackendClient } from "@/lib/backend-client";
import { useSubscription } from "@/lib/subscription-context";
import { usePlan } from "@/lib/hooks/use-gateway-data";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/data-viz";
import { SectionHeader } from "@/components/ui/section-header";
import { useToast } from "@/components/ui/toast";
import { BillingSkeleton } from "@/components/ui/skeleton";

// ---------------------------------------------------------------------------
// Plan definitions
// ---------------------------------------------------------------------------

interface PlanFeature {
  label: string;
}

interface PlanDefinition {
  tier: "pro" | "team";
  name: string;
  price: string;
  period: string;
  description: string;
  features: PlanFeature[];
  highlightColor: string;
}

const PLANS: PlanDefinition[] = [
  {
    tier: "pro",
    name: "pro",
    price: "$29",
    period: "/month",
    description: "for individual developers and small projects",
    features: [
      { label: "10 api keys" },
      { label: "standard rate limits" },
      { label: "email support" },
      { label: "audit logs (30 days)" },
    ],
    highlightColor: "var(--color-success)",
  },
  {
    tier: "team",
    name: "team",
    price: "$99",
    period: "/month",
    description: "for teams that need more scale and control",
    features: [
      { label: "50 api keys" },
      { label: "higher rate limits" },
      { label: "priority support" },
      { label: "audit logs (90 days)" },
      { label: "team management" },
    ],
    highlightColor: "var(--color-warning)",
  },
];

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
// Plan card for upgrade options
// ---------------------------------------------------------------------------

function PlanCard({
  plan,
  onUpgrade,
  upgrading,
}: {
  plan: PlanDefinition;
  onUpgrade: (tier: "pro" | "team") => void;
  upgrading: string | null;
}) {
  const isUpgrading = upgrading === plan.tier;
  const Icon = plan.tier === "pro" ? Zap : Users;

  return (
    <div
      className="flex-1 border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 hover:border-[var(--color-border-hover)] transition-all"
      style={{ borderTopColor: plan.highlightColor, borderTopWidth: "2px" }}
    >
      {/* Plan header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon
            className="w-3.5 h-3.5"
            style={{ color: plan.highlightColor }}
            strokeWidth={1.5}
          />
          <span className="text-[12px] uppercase tracking-[0.15em] text-[var(--color-text-muted)]">
            {plan.name}
          </span>
        </div>
        <div className="flex items-baseline gap-0.5">
          <span
            className="text-xl font-bold tracking-tight"
            style={{ color: plan.highlightColor }}
          >
            {plan.price}
          </span>
          <span className="text-[12px] text-[var(--color-text-dim)]">
            {plan.period}
          </span>
        </div>
      </div>

      <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed mb-4">
        {plan.description}
      </p>

      {/* Features list */}
      <ul className="space-y-2 mb-5">
        {plan.features.map((f) => (
          <li key={f.label} className="flex items-center gap-2">
            <CheckCircle2
              className="w-3 h-3 flex-shrink-0"
              style={{ color: plan.highlightColor }}
              strokeWidth={1.5}
            />
            <span className="text-[12px] text-[var(--color-text-muted)] tracking-wider">
              {f.label}
            </span>
          </li>
        ))}
      </ul>

      {/* Upgrade button */}
      <button
        onClick={() => onUpgrade(plan.tier)}
        disabled={isUpgrading || upgrading !== null}
        className="w-full flex items-center justify-center gap-2 px-4 py-2 text-[12px] tracking-wider uppercase border transition-all disabled:opacity-40"
        style={{
          borderColor: plan.highlightColor,
          color: plan.highlightColor,
        }}
      >
        {isUpgrading ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : (
          <ArrowRight className="w-3 h-3" />
        )}
        {isUpgrading ? "redirecting..." : `upgrade to ${plan.name}`}
      </button>
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
      <div className="p-8 max-w-3xl animate-fade-in">
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
  const { data: plan } = usePlan();
  const planTier = plan?.tier ?? "free";
  const maxApiKeys = plan?.limits.api_keys === "unlimited" ? "∞" : (plan?.limits.api_keys ?? 1);
  const searchParams = useSearchParams();
  const { toast } = useToast();

  const [upgrading, setUpgrading] = useState<string | null>(null);
  const [managingPortal, setManagingPortal] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Determine checkout outcome from URL params (set by S6 suggestion)
  const checkoutOutcome = searchParams.get("checkout");

  // Refetch subscription after successful checkout return
  useEffect(() => {
    if (checkoutOutcome === "success") {
      refetch();
    }
  }, [checkoutOutcome, refetch]);

  const handleUpgrade = useCallback(
    async (tier: "pro" | "team") => {
      setActionError(null);
      setUpgrading(tier);
      try {
        const origin = window.location.origin;
        const successUrl = `${origin}/settings/billing?checkout=success`;
        const cancelUrl = `${origin}/settings/billing?checkout=canceled`;
        const { checkout_url } = await client.createCheckoutSession(
          tier,
          successUrl,
          cancelUrl,
        );
        window.location.href = checkout_url;
      } catch (e) {
        setActionError(String(e));
        toast("failed to start checkout", "error");
        setUpgrading(null);
      }
    },
    [client, toast],
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

  // Format period-end date when available — not present in SubscriptionState,
  // so we rely on the context's status/planTier only
  const statusLabel = status === "active"
    ? "active"
    : status === "past_due"
      ? "past due"
      : status === "canceled"
        ? "canceled"
        : status;

  return (
    <div className="p-8 max-w-3xl animate-fade-in">
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

      {/* Upgrade section — only shown when on free tier */}
      {isFreeTier && (
        <section className="mb-8">
          <SectionHeader icon={Zap} title="upgrade plan" />
          <div className="flex gap-4">
            {PLANS.map((plan) => (
              <PlanCard
                key={plan.tier}
                plan={plan}
                onUpgrade={handleUpgrade}
                upgrading={upgrading}
              />
            ))}
          </div>
          <p className="mt-3 text-[11px] text-[var(--color-text-dim)] tracking-wider">
            all plans billed monthly. cancel anytime. prices in usd.
          </p>
        </section>
      )}
    </div>
  );
}
