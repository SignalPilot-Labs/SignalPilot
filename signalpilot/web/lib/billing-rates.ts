/**
 * Credit rate helpers. 1 credit = $0.01. No volume brackets.
 *
 * There are no numbers in this file. Pricing lives in Stripe; the backend
 * reads it and publishes it on `GET /api/v1/billing/plans` (`RateCard` and
 * the plan table), and the billing and usage pages render from that
 * response only. The ledger in the backend is the source of truth for what
 * was charged.
 */

import type { PlanInfo, RateCard } from "~/lib/backend-client";

export type { RateCard } from "~/lib/backend-client";

export type CreditUnit =
  | "thread"
  | "query"
  | "model_day"
  | "eval_run"
  | "seat_day"
  | "tokens";

export interface CreditRate {
  unit: CreditUnit;
  label: string;
  /** Credits per unit; null when priced at cost (tokens) or set by contract (seats). */
  credits: number | null;
  per: string;
  note: string;
}

/**
 * Build the display rows of the rate table from a rate card. The seat row
 * belongs to a plan (each plan product carries its own seat rate; a plan
 * without one prices seats in the contract), so it is passed separately.
 */
export function creditRatesFrom(
  rates: RateCard,
  seatMonthCredits: number | null | undefined = undefined,
): CreditRate[] {
  const rows: CreditRate[] = [
    {
      unit: "thread",
      label: "Successful thread",
      credits: rates.thread_credits,
      per: "thread",
      note: "Failed, zero-query, low-evidence, repeat and tuning threads deduct nothing.",
    },
    {
      unit: "query",
      label: "Governed query",
      credits: rates.query_credits,
      per: "query",
      note: "Everywhere: thread, Claude Code, notebook, schedule, eval run.",
    },
    {
      unit: "model_day",
      label: "Covered data model beyond allowance",
      credits: rates.model_month_credits,
      per: "model-month",
      note: `Metered daily as ${rates.model_month_credits.toLocaleString("en-US")} divided by days in the month.`,
    },
    {
      unit: "eval_run",
      label: "Eval run beyond allowance",
      credits: rates.eval_run_credits,
      per: "run",
      note: "Runs inside the plan allowance are included. Queries inside a run deduct as queries.",
    },
  ];
  if (seatMonthCredits !== undefined) {
    rows.push({
      unit: "seat_day",
      label: "Added seat beyond allowance",
      credits: seatMonthCredits,
      per: "seat-month",
      note:
        seatMonthCredits === null
          ? "Seats beyond the allowance are priced in your contract."
          : "Metered daily like models. Invited but not accepted members do not count.",
    });
  }
  rows.push({
    unit: "tokens",
    label: "Model tokens on the platform key",
    credits: null,
    per: "run",
    note: `Provider list price times ${rates.token_credits_per_dollar.toLocaleString("en-US")}. Bring your own key and tokens deduct nothing.`,
  });
  return rows;
}

export const UNIT_LABELS: Record<string, string> = {
  thread: "threads",
  query: "queries",
  model_day: "model-days",
  eval_run: "eval runs",
  seat_day: "seat-days",
  tokens: "model tokens",
  included: "included",
  enterprise: "enterprise grant",
  manual: "manual",
};

/** The plan a paid org is on, from the published list; null until it loads. */
export function planForTier(plans: PlanInfo[] | null, tier: string): PlanInfo | null {
  return plans?.find((p) => p.tier === tier) ?? null;
}

/**
 * 1 credit = $0.01 is the ledger's unit contract (credits are integer cents),
 * not a price, so it is the default here; a rate card only restates it.
 */
export function creditsToUsd(credits: number, rates?: Pick<RateCard, "credit_cents"> | null): number {
  return (credits * (rates?.credit_cents ?? 1)) / 100;
}

export function centsToUsd(cents: number): number {
  return cents / 100;
}

export function formatCredits(credits: number): string {
  return Math.round(credits).toLocaleString("en-US");
}

export function formatUsd(amount: number): string {
  const hasCents = Math.abs(amount % 1) > 0.000001;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: hasCents ? 2 : 0,
    maximumFractionDigits: hasCents ? 2 : 0,
  }).format(amount);
}
