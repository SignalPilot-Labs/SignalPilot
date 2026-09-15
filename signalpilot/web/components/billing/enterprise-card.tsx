"use client";

import { Building2, CheckCircle2, Mail } from "lucide-react";
import type { PlanInfo } from "~/lib/backend-client";
import { PLAN_ALLOWANCES, formatCredits } from "~/lib/billing-rates";
import type { Entitlement } from "~/lib/entitlement";
import { AllowanceList, formatPrice } from "~/components/billing/plan-card";

/** The one contact route for Enterprise; there is no self-serve path. */
export const ENTERPRISE_CONTACT = "mailto:daniel@signalpilot.ai?subject=SignalPilot%20Enterprise";

const ENTERPRISE_FEATURES = [
  "sso (saml/oidc) and scim",
  "privatelink and customer-managed keys",
  "custom sla and audit export cadence",
  "managed precision guarantee available",
  "invoice billing with purchase order",
];

const ACCENT = "var(--color-text-muted)";

/**
 * Enterprise is priced to the estate and never self-served: the card has no
 * buy button, only "Contact us". When the org is already on Enterprise the
 * card is marked current and the contact link is the route for changes.
 */
export function EnterpriseCard({
  plan,
  isCurrent,
}: {
  /** The enterprise plan from the backend when it publishes one. */
  plan: PlanInfo | null;
  isCurrent: boolean;
}) {
  const fallback = PLAN_ALLOWANCES.enterprise;
  const allowances = plan ?? {
    included_seats: fallback.seats,
    included_models: fallback.models,
    included_eval_runs: fallback.evalRuns,
    included_credits: fallback.credits,
  };
  const fromCents = plan?.monthly_fee_cents ?? fallback.monthlyFeeCents;

  return (
    <div
      data-testid="plan-card-enterprise"
      className="flex-1 border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-5 hover:border-[var(--color-border-hover)] transition-colors duration-150"
      style={{ borderTopColor: ACCENT, borderTopWidth: "2px" }}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <Building2 className="w-3.5 h-3.5 text-[var(--color-text-muted)]" strokeWidth={1.5} />
          <span className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
            {plan?.name ?? "enterprise"}
          </span>
        </div>
        <div className="text-right">
          <div className="flex items-baseline gap-0.5">
            <span
              data-testid="plan-price"
              className="text-xl font-bold font-mono tracking-tight tabular-nums text-[var(--color-text-muted)]"
            >
              from {formatPrice(fromCents, "usd")}
            </span>
            <span className="text-[12px] text-[var(--color-text-dim)]">/mo</span>
          </div>
          <span className="text-[11px] text-[var(--color-text-dim)] font-mono">billed monthly</span>
        </div>
      </div>

      <p className="text-[12px] text-[var(--color-text-dim)] leading-relaxed mb-4">
        Priced to your estate, one purchase order
      </p>

      <AllowanceList plan={allowances} color={ACCENT} moreByAgreement />

      <ul className="space-y-2 mb-5">
        {ENTERPRISE_FEATURES.map((f) => (
          <li key={f} className="flex items-center gap-2">
            <CheckCircle2 className="w-3 h-3 flex-shrink-0 text-[var(--color-text-muted)]" strokeWidth={1.5} />
            <span className="text-[12px] text-[var(--color-text-muted)]">{f}</span>
          </li>
        ))}
      </ul>

      {isCurrent && (
        <div
          data-testid="plan-current"
          className="w-full flex items-center justify-center gap-2 px-4 py-2 mb-2 text-[12px] border rounded-[10px]"
          style={{ borderColor: ACCENT, color: ACCENT, opacity: 0.7 }}
        >
          <CheckCircle2 className="w-3 h-3" />
          Current plan
        </div>
      )}
      <a
        data-testid="enterprise-contact"
        href={ENTERPRISE_CONTACT}
        className="w-full flex items-center justify-center gap-2 px-4 py-2 text-[12px] border rounded-[10px] border-[var(--color-text-muted)] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] transition-colors duration-150"
      >
        <Mail className="w-3 h-3" />
        {isCurrent ? "Contact us for changes" : "Contact us"}
      </a>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Contract summary — the entitlement row for an enterprise org
// ---------------------------------------------------------------------------

function contractField(contract: Record<string, unknown> | null, key: string): string | null {
  const v = contract?.[key];
  if (v === null || v === undefined || v === "") return null;
  return typeof v === "string" ? v : JSON.stringify(v);
}

export function EnterpriseContractSummary({
  entitlement,
  contract,
  currentPeriodEnd,
}: {
  entitlement: Entitlement;
  contract: Record<string, unknown> | null;
  currentPeriodEnd: string | null;
}) {
  const flags = Object.entries(entitlement.enterpriseFlags).filter(([, v]) => v === true);
  const rows: Array<[string, string]> = [
    ["seats included", entitlement.includedSeats.toLocaleString("en-US")],
    ["covered models included", entitlement.includedModels.toLocaleString("en-US")],
    ["eval runs per month", entitlement.includedEvalRuns.toLocaleString("en-US")],
    ["credits per month", formatCredits(entitlement.includedCredits)],
    ["managed", entitlement.managed ? "yes" : "no"],
  ];
  const legalName = contractField(contract, "legal_name");
  const po = contractField(contract, "po_number");
  const terms = contractField(contract, "payment_terms");
  const termEnd = contractField(contract, "term_end") ?? currentPeriodEnd;
  if (legalName) rows.push(["contract", legalName]);
  if (po) rows.push(["purchase order", po]);
  if (terms) rows.push(["payment terms", terms]);
  if (termEnd) {
    rows.push([
      "renews",
      new Date(termEnd).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" }),
    ]);
  }

  return (
    <div
      data-testid="enterprise-contract"
      className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-5"
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-2">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between py-1.5 border-b border-[var(--color-border)]">
            <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">{label}</span>
            <span className="text-[12px] text-[var(--color-text)] font-mono tabular-nums">{value}</span>
          </div>
        ))}
      </div>
      {flags.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {flags.map(([name]) => (
            <span
              key={name}
              className="px-2 py-1 text-[11px] border border-[var(--color-border)] rounded-[8px] text-[var(--color-text-muted)]"
            >
              {name.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      )}
      <p className="mt-4 text-[11px] text-[var(--color-text-dim)]">
        changes to the contract go through your account team ·{" "}
        <a href={ENTERPRISE_CONTACT} className="underline hover:text-[var(--color-text)]">
          contact us
        </a>
        . usage beyond the contract is metered at the standard credit rates.
      </p>
    </div>
  );
}
