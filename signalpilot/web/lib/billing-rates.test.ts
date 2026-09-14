import { describe, expect, it } from "vitest";

import {
  CREDIT_RATES,
  PLAN_ALLOWANCES,
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
  it("matches the published fixed rates, no brackets", () => {
    expect(rate("thread").credits).toBe(50);
    expect(rate("query").credits).toBe(1);
    expect(rate("model_day").credits).toBe(600);
    expect(rate("eval_run").credits).toBe(50);
    expect(rate("seat_day").credits).toBe(1000);
    expect(rate("seat_day").enterpriseCredits).toBe(1500);
    expect(rate("tokens").credits).toBeNull();
  });

  it("publishes the plan allowances and included credit blocks", () => {
    expect(PLAN_ALLOWANCES.team).toEqual({ seats: 10, models: 30, evalRuns: 30, credits: 5_000 });
    expect(PLAN_ALLOWANCES.scale).toEqual({ seats: 25, models: 50, evalRuns: 30, credits: 12_500 });
    expect(PLAN_ALLOWANCES.enterprise).toEqual({ seats: 100, models: 100, evalRuns: 30, credits: 75_000 });
  });

  it("converts credits at one cent each", () => {
    expect(creditsToUsd(50)).toBeCloseTo(0.5);
    expect(formatUsd(creditsToUsd(600))).toBe("$6");
    expect(formatUsd(creditsToUsd(1))).toBe("$0.01");
    expect(formatCredits(12_500)).toBe("12,500");
  });
});
