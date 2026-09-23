/**
 * Pure helpers behind the plan cards and the "Review your plan" dialog.
 *
 * Everything a customer will actually pay (the term's fee, added seats,
 * credits, due today) is computed here from the plan as Stripe publishes it
 * and the rate card, so the dialog and its tests share one source. A plan
 * offers the terms whose prices are active in Stripe: "year" is the
 * published term, "quarter" the three-month option at a premium.
 */

import type { BillingInterval, PlanInfo, PlanPrice, RateCard } from "~/lib/backend-client";
import { formatCredits, formatUsd } from "~/lib/billing-rates";

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
// Prices and terms
// ---------------------------------------------------------------------------

/** Terms in the order they are offered: the published yearly term first. */
export const TERM_ORDER: readonly BillingInterval[] = ["year", "quarter", "month"];

export const TERM_LABEL: Record<BillingInterval, string> = {
  year: "billed yearly",
  quarter: "billed every 3 months",
  month: "billed monthly",
};

export const TERM_NAME: Record<BillingInterval, string> = {
  year: "Annual",
  quarter: "3 months",
  month: "Monthly",
};

/** The plan's price for one term, or null when Stripe does not offer it. */
export function priceFor(plan: Pick<PlanInfo, "prices">, interval: BillingInterval): PlanPrice | null {
  return plan.prices.find((p) => p.interval === interval) ?? null;
}

/** The plan's prices in offer order. */
export function offeredPrices(plan: Pick<PlanInfo, "prices">): PlanPrice[] {
  return TERM_ORDER.map((t) => priceFor(plan, t)).filter((p): p is PlanPrice => p !== null);
}

/** The term bought by default: the first offered one (yearly when it exists). */
export function defaultPrice(plan: Pick<PlanInfo, "prices">): PlanPrice | null {
  return offeredPrices(plan)[0] ?? null;
}

/** What one payment of ``price`` works out to per month. */
export function monthlyEquivalentCents(price: PlanPrice): number {
  return Math.round(price.amount / Math.max(1, price.months));
}

/** The published fee per month: the yearly term's monthly equivalent, else the plan's figure, else the cheapest term. */
export function monthlyFeeCents(plan: Pick<PlanInfo, "prices" | "monthly_fee_cents">): number | null {
  const year = priceFor(plan, "year");
  if (year) return monthlyEquivalentCents(year);
  if (plan.monthly_fee_cents !== null) return plan.monthly_fee_cents;
  const cheapest = offeredPrices(plan).map(monthlyEquivalentCents).sort((a, b) => a - b)[0];
  return cheapest ?? null;
}

/** e.g. "$250/mo · $3,000 billed yearly" or "$300/mo · $900 billed every 3 months". */
export function feeLine(price: PlanPrice): string {
  const perMonth = formatPrice(monthlyEquivalentCents(price), price.currency);
  if (price.months <= 1) return `${perMonth}/mo, ${TERM_LABEL[price.interval]}`;
  return `${perMonth}/mo · ${formatPrice(price.amount, price.currency)} ${TERM_LABEL[price.interval]}`;
}

// ---------------------------------------------------------------------------
// Seats
// ---------------------------------------------------------------------------

export interface SeatEstimate {
  /** Members in the org as Clerk reports them; null when unknown (local mode, not loaded). */
  members: number | null;
  included: number;
  added: number;
  /** Credits per added seat-month; null when seats are priced in the contract. */
  seatMonthCredits: number | null;
  creditsPerMonth: number;
  usdPerMonth: number;
}

export function seatEstimate(
  plan: Pick<PlanInfo, "included_seats" | "seat_month_credits">,
  members: number | null,
  rates: RateCard | null = null,
): SeatEstimate {
  const included = plan.included_seats;
  const added = members === null ? 0 : Math.max(0, members - included);
  const rate = plan.seat_month_credits;
  const creditsPerMonth = rate === null ? 0 : added * rate;
  const creditCents = rates?.credit_cents ?? 1;
  return {
    members,
    included,
    added,
    seatMonthCredits: rate,
    creditsPerMonth,
    usdPerMonth: (creditsPerMonth * creditCents) / 100,
  };
}

/** The seat lines of the dialog, in order. */
export function seatLines(est: SeatEstimate): string[] {
  if (est.members === null) {
    return [
      est.seatMonthCredits === null
        ? `Seats beyond the ${est.included.toLocaleString("en-US")} included are priced in your contract.`
        : `Seats are counted daily; members beyond the ${est.included.toLocaleString("en-US")} included use credits (${formatCredits(
            est.seatMonthCredits,
          )} credits per seat-month).`,
    ];
  }
  const lines = [
    `Your organization has ${est.members.toLocaleString("en-US")} ${est.members === 1 ? "member" : "members"} · ${est.included.toLocaleString(
      "en-US",
    )} included · ${est.added.toLocaleString("en-US")} added ${est.added === 1 ? "seat" : "seats"}`,
  ];
  if (est.added > 0 && est.seatMonthCredits !== null) {
    lines.push(
      `${est.added.toLocaleString("en-US")} × ${formatCredits(est.seatMonthCredits)} credits/month (≈ ${formatUsd(
        est.usdPerMonth,
      )}/mo) drawn from your credits`,
    );
  } else if (est.added > 0) {
    lines.push("Added seats are priced in your contract.");
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
