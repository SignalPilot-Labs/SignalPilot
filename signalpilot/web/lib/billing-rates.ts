/**
 * The fixed credit rate card. 1 credit = $0.01. No volume brackets.
 *
 * `GET /api/v1/billing/plans` publishes the live `RateCard` and plan table;
 * the constants here are a typed fallback with the same numbers so the
 * billing and usage pages can render before (or without) that response.
 * The ledger in the backend is the source of truth for what was charged.
 */

import type { PaidTier, RateCard } from "~/lib/backend-client";

export type { RateCard } from "~/lib/backend-client";

/** Fallback rate card, identical to the backend's `app/billing/rates.py`. */
export const DEFAULT_RATE_CARD: RateCard = {
  credit_cents: 1,
  thread_credits: 50,
  query_credits: 1,
  model_month_credits: 600,
  eval_run_credits: 50,
  seat_month_credits: 1000,
  enterprise_seat_month_credits: 1500,
  token_credits_per_dollar: 100,
  overage_cents_per_credit: 1,
};

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
  /** Credits per unit; null when priced at cost (tokens). */
  credits: number | null;
  /** Credits per unit on Enterprise when it differs. */
  enterpriseCredits?: number;
  per: string;
  note: string;
}

/** Build the display rows of the rate table from a rate card. */
export function creditRatesFrom(rates: RateCard): CreditRate[] {
  return [
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
    {
      unit: "seat_day",
      label: "Added seat beyond allowance",
      credits: rates.seat_month_credits,
      enterpriseCredits: rates.enterprise_seat_month_credits,
      per: "seat-month",
      note: "Metered daily like models. Invited but not accepted members do not count.",
    },
    {
      unit: "tokens",
      label: "Model tokens on the platform key",
      credits: null,
      per: "run",
      note: `Provider list price times ${rates.token_credits_per_dollar.toLocaleString("en-US")}. Bring your own key and tokens deduct nothing.`,
    },
  ];
}

export const CREDIT_RATES: readonly CreditRate[] = creditRatesFrom(DEFAULT_RATE_CARD);

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

export interface PlanAllowances {
  seats: number;
  models: number;
  evalRuns: number;
  credits: number;
  monthlyFeeCents: number;
  seatMonthCredits: number;
  managedFromCents: number;
}

/**
 * Published plan table, identical to the backend's `PLAN_RATES`; the
 * entitlement row can raise the allowances by agreement.
 */
export const PLAN_ALLOWANCES: Record<PaidTier, PlanAllowances> = {
  team: {
    seats: 10,
    models: 30,
    evalRuns: 30,
    credits: 5_000,
    monthlyFeeCents: 100_00,
    seatMonthCredits: 1000,
    managedFromCents: 1_500_00,
  },
  scale: {
    seats: 25,
    models: 50,
    evalRuns: 30,
    credits: 12_500,
    monthlyFeeCents: 250_00,
    seatMonthCredits: 1000,
    managedFromCents: 2_500_00,
  },
  enterprise: {
    seats: 100,
    models: 100,
    evalRuns: 30,
    credits: 75_000,
    monthlyFeeCents: 1_500_00,
    seatMonthCredits: 1500,
    managedFromCents: 5_000_00,
  },
};

export function creditsToUsd(credits: number, rates: RateCard = DEFAULT_RATE_CARD): number {
  return (credits * rates.credit_cents) / 100;
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
