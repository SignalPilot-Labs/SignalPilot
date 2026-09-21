import { describe, expect, it } from "vitest";

import type { PlanInfo, RateCard } from "~/lib/backend-client";
import {
  centsToUsd,
  creditRatesFrom,
  creditsToUsd,
  formatCredits,
  formatUsd,
  planForTier,
} from "~/lib/billing-rates";

/** A rate card as the backend reads it from the Stripe Credits product. */
export const LIVE_RATES: RateCard = {
  credit_cents: 1,
  thread_credits: 50,
  query_credits: 1,
  model_month_credits: 600,
  eval_run_credits: 50,
  token_credits_per_dollar: 100,
  overage_cents_per_credit: 1,
  version: "2",
};

describe("credit rate card", () => {
  it("carries no numbers of its own: rows come from the live card", () => {
    const live: RateCard = { ...LIVE_RATES, thread_credits: 40, model_month_credits: 900, token_credits_per_dollar: 120 };
    const rows = creditRatesFrom(live, 1500);
    const byUnit = Object.fromEntries(rows.map((r) => [r.unit, r]));
    expect(byUnit.thread.credits).toBe(40);
    expect(byUnit.query.credits).toBe(1);
    expect(byUnit.model_day.credits).toBe(900);
    expect(byUnit.model_day.note).toContain("900");
    expect(byUnit.eval_run.credits).toBe(50);
    expect(byUnit.seat_day.credits).toBe(1500);
    expect(byUnit.tokens.credits).toBeNull();
    expect(byUnit.tokens.note).toContain("120");
    expect(rows.map((r) => r.unit)).toEqual(["thread", "query", "model_day", "eval_run", "seat_day", "tokens"]);
  });

  it("shows the seat row as contracted when the plan has no public seat price, and hides it without a plan", () => {
    const contracted = creditRatesFrom(LIVE_RATES, null).find((r) => r.unit === "seat_day");
    expect(contracted?.credits).toBeNull();
    expect(contracted?.note).toContain("contract");
    expect(creditRatesFrom(LIVE_RATES).map((r) => r.unit)).not.toContain("seat_day");
  });

  it("finds the current plan in the published list", () => {
    const team = { tier: "team" } as PlanInfo;
    expect(planForTier([team], "team")).toBe(team);
    expect(planForTier([team], "scale")).toBeNull();
    expect(planForTier(null, "team")).toBeNull();
  });

  it("converts credits at one cent each (the ledger unit), or at the live credit_cents", () => {
    expect(creditsToUsd(50)).toBeCloseTo(0.5);
    expect(creditsToUsd(50, { credit_cents: 2 })).toBeCloseTo(1);
    expect(centsToUsd(1234)).toBeCloseTo(12.34);
    expect(formatUsd(creditsToUsd(600))).toBe("$6");
    expect(formatUsd(creditsToUsd(1))).toBe("$0.01");
    expect(formatCredits(12_500)).toBe("12,500");
  });
});
