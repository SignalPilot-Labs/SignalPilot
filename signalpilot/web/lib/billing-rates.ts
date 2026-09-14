/**
 * The fixed credit rate card. 1 credit = $0.01. No volume brackets.
 *
 * These numbers are display constants for the billing and usage pages; the
 * ledger in the gateway is the source of truth for what was charged.
 */

export const CREDIT_USD = 0.01;

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

export const CREDIT_RATES: readonly CreditRate[] = [
  {
    unit: "thread",
    label: "Successful thread",
    credits: 50,
    per: "thread",
    note: "Failed, zero-query, low-evidence, repeat and tuning threads deduct nothing.",
  },
  {
    unit: "query",
    label: "Governed query",
    credits: 1,
    per: "query",
    note: "Everywhere: thread, Claude Code, notebook, schedule, eval run.",
  },
  {
    unit: "model_day",
    label: "Covered data model beyond allowance",
    credits: 600,
    per: "model-month",
    note: "Metered daily as 600 divided by days in the month.",
  },
  {
    unit: "eval_run",
    label: "Eval run beyond allowance",
    credits: 50,
    per: "run",
    note: "The first 30 runs each period are included. Queries inside a run deduct as queries.",
  },
  {
    unit: "seat_day",
    label: "Added seat beyond allowance",
    credits: 1000,
    enterpriseCredits: 1500,
    per: "seat-month",
    note: "Metered daily like models. Invited but not accepted members do not count.",
  },
  {
    unit: "tokens",
    label: "Model tokens on the platform key",
    credits: null,
    per: "run",
    note: "Provider list price times 100. Bring your own key and tokens deduct nothing.",
  },
];

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
}

/** Published allowances per plan; the entitlement row can raise them by agreement. */
export const PLAN_ALLOWANCES: Record<"team" | "scale" | "enterprise", PlanAllowances> = {
  team: { seats: 10, models: 30, evalRuns: 30, credits: 5_000 },
  scale: { seats: 25, models: 50, evalRuns: 30, credits: 12_500 },
  enterprise: { seats: 100, models: 100, evalRuns: 30, credits: 75_000 },
};

export function creditsToUsd(credits: number): number {
  return credits * CREDIT_USD;
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
