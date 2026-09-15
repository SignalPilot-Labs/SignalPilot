import { describe, expect, it } from "vitest";

import type { RateCard } from "~/lib/backend-client";
import {
  CREDIT_RATES,
  DEFAULT_RATE_CARD,
  PLAN_ALLOWANCES,
  centsToUsd,
  creditRatesFrom,
  creditsToUsd,
  formatCredits,
  formatUsd,
} from "~/lib/billing-rates";

function rate(unit: string) {
  const r = CREDIT_RATES.find((x) => x.unit === unit);
  if (!r) throw new Error(`no rate for ${unit}`);
  return r;
}

describe("credit rate card", () => {
  it("fallback rate card mirrors the backend RateCard shape and numbers", () => {
    expect(DEFAULT_RATE_CARD).toEqual({
      credit_cents: 1,
      thread_credits: 50,
      query_credits: 1,
      model_month_credits: 600,
      eval_run_credits: 50,
      seat_month_credits: 1000,
      enterprise_seat_month_credits: 1500,
      token_credits_per_dollar: 100,
      overage_cents_per_credit: 1,
    });
  });

  it("matches the published fixed rates, no brackets", () => {
    expect(rate("thread").credits).toBe(50);
    expect(rate("query").credits).toBe(1);
    expect(rate("model_day").credits).toBe(600);
    expect(rate("eval_run").credits).toBe(50);
    expect(rate("seat_day").credits).toBe(1000);
    expect(rate("seat_day").enterpriseCredits).toBe(1500);
    expect(rate("tokens").credits).toBeNull();
  });

  it("builds the rate rows from a live rate card in the backend shape", () => {
    const live: RateCard = {
      ...DEFAULT_RATE_CARD,
      thread_credits: 40,
      model_month_credits: 900,
      enterprise_seat_month_credits: 2000,
      token_credits_per_dollar: 120,
    };
    const rows = creditRatesFrom(live);
    const byUnit = Object.fromEntries(rows.map((r) => [r.unit, r]));
    expect(byUnit.thread.credits).toBe(40);
    expect(byUnit.model_day.credits).toBe(900);
    expect(byUnit.model_day.note).toContain("900");
    expect(byUnit.seat_day.enterpriseCredits).toBe(2000);
    expect(byUnit.tokens.note).toContain("120");
    expect(rows.map((r) => r.unit)).toEqual([
      "thread",
      "query",
      "model_day",
      "eval_run",
      "seat_day",
      "tokens",
    ]);
  });

  it("publishes the plan allowances, fees and included credit blocks", () => {
    expect(PLAN_ALLOWANCES.team).toEqual({
      seats: 10,
      models: 30,
      evalRuns: 30,
      credits: 5_000,
      monthlyFeeCents: 10_000,
      seatMonthCredits: 1000,
      managedFromCents: 150_000,
    });
    expect(PLAN_ALLOWANCES.scale).toEqual({
      seats: 25,
      models: 50,
      evalRuns: 30,
      credits: 12_500,
      monthlyFeeCents: 25_000,
      seatMonthCredits: 1000,
      managedFromCents: 250_000,
    });
    expect(PLAN_ALLOWANCES.enterprise).toEqual({
      seats: 100,
      models: 100,
      evalRuns: 30,
      credits: 75_000,
      monthlyFeeCents: 150_000,
      seatMonthCredits: 1500,
      managedFromCents: 500_000,
    });
  });

  it("converts credits at one cent each, or at the live credit_cents", () => {
    expect(creditsToUsd(50)).toBeCloseTo(0.5);
    expect(creditsToUsd(50, { ...DEFAULT_RATE_CARD, credit_cents: 2 })).toBeCloseTo(1);
    expect(centsToUsd(1234)).toBeCloseTo(12.34);
    expect(formatUsd(creditsToUsd(600))).toBe("$6");
    expect(formatUsd(creditsToUsd(1))).toBe("$0.01");
    expect(formatCredits(12_500)).toBe("12,500");
  });
});
