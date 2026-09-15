/**
 * Pure helpers behind the plan cards and the "Review your plan" dialog.
 *
 * Billing is monthly only: the cards show one published monthly price for
 * everyone, and everything a customer will actually pay (added seats,
 * credits, due today) is computed here from the plan's monthly Stripe price
 * and the rate card, so the dialog and its tests share one source.
 */

import type { PlanInfo, PlanPrice, RateCard } from "~/lib/backend-client";
import { DEFAULT_RATE_CARD, formatCredits, formatUsd } from "~/lib/billing-rates";

// ---------------------------------------------------------------------------
// Money
// ---------------------------------------------------------------------------

export function formatPrice(amountCents: number, currency = "usd"): string {
  const dollars = amountCents / 100;
  const hasCents = Math.abs(dollars % 1) > 0.000001;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: hasCents ? 2 : 0,
    maximumFractionDigits: hasCents ? 2 : 0,
  }).format(dollars);
}

// ---------------------------------------------------------------------------
// Prices
// ---------------------------------------------------------------------------

/** The plan's monthly Stripe price; any other interval the API returns is ignored. */
export function monthlyPrice(plan: Pick<PlanInfo, "prices">): PlanPrice | null {
  return plan.prices.find((p) => p.interval === "month") ?? null;
}

/** The published monthly fee: the Stripe monthly price, else the static flat fee. */
export function monthlyFeeCents(plan: Pick<PlanInfo, "prices" | "monthly_fee_cents">): number {
  return monthlyPrice(plan)?.amount ?? plan.monthly_fee_cents;
}

/** e.g. "$250/mo, billed monthly" */
export function feeLine(plan: Pick<PlanInfo, "prices" | "monthly_fee_cents">): string {
  const price = monthlyPrice(plan);
  return `${formatPrice(monthlyFeeCents(plan), price?.currency ?? "usd")}/mo, billed monthly`;
}

// ---------------------------------------------------------------------------
// Seats
// ---------------------------------------------------------------------------

export interface SeatEstimate {
  /** Members in the org as Clerk reports them; null when unknown (local mode, not loaded). */
  members: number | null;
  included: number;
  added: number;
  seatMonthCredits: number;
  creditsPerMonth: number;
  usdPerMonth: number;
}

export function seatEstimate(
  plan: Pick<PlanInfo, "included_seats" | "seat_month_credits">,
  members: number | null,
  rates: RateCard | null = null,
): SeatEstimate {
  const card = rates ?? DEFAULT_RATE_CARD;
  const included = plan.included_seats;
  const added = members === null ? 0 : Math.max(0, members - included);
  const creditsPerMonth = added * plan.seat_month_credits;
  return {
    members,
    included,
    added,
    seatMonthCredits: plan.seat_month_credits,
    creditsPerMonth,
    usdPerMonth: (creditsPerMonth * card.credit_cents) / 100,
  };
}

/** The seat lines of the dialog, in order. */
export function seatLines(est: SeatEstimate): string[] {
  if (est.members === null) {
    return [
      `Seats are counted daily; members beyond the ${est.included.toLocaleString("en-US")} included use credits (${formatCredits(
        est.seatMonthCredits,
      )} credits per seat-month).`,
    ];
  }
  const lines = [
    `Your organization has ${est.members.toLocaleString("en-US")} ${est.members === 1 ? "member" : "members"} · ${est.included.toLocaleString(
      "en-US",
    )} included · ${est.added.toLocaleString("en-US")} added ${est.added === 1 ? "seat" : "seats"}`,
  ];
  if (est.added > 0) {
    lines.push(
      `${est.added.toLocaleString("en-US")} × ${formatCredits(est.seatMonthCredits)} credits/month (≈ ${formatUsd(
        est.usdPerMonth,
      )}/mo) drawn from your credits`,
    );
  }
  return lines;
}

// ---------------------------------------------------------------------------
// Allowances
// ---------------------------------------------------------------------------

export function includedLine(
  plan: Pick<PlanInfo, "included_credits" | "included_models" | "included_eval_runs">,
): string {
  return `Included every month: ${formatCredits(plan.included_credits)} credits, ${plan.included_models.toLocaleString(
    "en-US",
  )} covered models, ${plan.included_eval_runs.toLocaleString("en-US")} eval runs`;
}

// ---------------------------------------------------------------------------
// Due today
// ---------------------------------------------------------------------------

export type ReviewMode = "checkout" | "upgrade" | "downgrade";

export interface ProrationPreview {
  amount_due: number;
  currency: string;
  credit: number;
  new_charge: number;
  immediate: boolean;
  effective_date: string | null;
}

export type DueToday =
  | { kind: "flat"; label: "Due today"; amountCents: number; currency: string }
  | { kind: "prorated"; label: "Due today (prorated)"; amountCents: number; currency: string; creditCents: number }
  | { kind: "renewal"; label: "No charge today"; detail: string }
  | { kind: "loading"; label: "Due today" };

export function formatRenewalDate(date: string | null): string | null {
  if (!date) return null;
  const iso = /^\d{4}-\d{2}-\d{2}$/.test(date) ? `${date}T00:00:00` : date;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
}

function renewal(date: string | null): DueToday {
  const when = formatRenewalDate(date);
  return {
    kind: "renewal",
    label: "No charge today",
    detail: when ? `changes at renewal on ${when}` : "changes at renewal",
  };
}

export function dueToday(input: {
  mode: ReviewMode;
  price: PlanPrice | null;
  proration: ProrationPreview | null;
  loadingPreview: boolean;
  currentPeriodEnd: string | null;
}): DueToday {
  const { mode, price, proration, loadingPreview, currentPeriodEnd } = input;
  if (mode === "checkout") {
    return {
      kind: "flat",
      label: "Due today",
      amountCents: price?.amount ?? 0,
      currency: price?.currency ?? "usd",
    };
  }
  if (mode === "downgrade") return renewal(proration?.effective_date ?? currentPeriodEnd);
  if (loadingPreview) return { kind: "loading", label: "Due today" };
  if (proration && !proration.immediate) return renewal(proration.effective_date ?? currentPeriodEnd);
  return {
    kind: "prorated",
    label: "Due today (prorated)",
    amountCents: proration?.amount_due ?? price?.amount ?? 0,
    currency: proration?.currency ?? price?.currency ?? "usd",
    creditCents: proration?.credit ?? 0,
  };
}

export function primaryButtonLabel(mode: ReviewMode): string {
  return mode === "checkout" ? "Continue to payment" : "Confirm change";
}
