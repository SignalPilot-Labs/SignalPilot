import { describe, expect, it } from "vitest";

import type { PlanInfo } from "~/lib/backend-client";
import {
  defaultPrice,
  dueToday,
  feeLine,
  includedLine,
  monthlyEquivalentCents,
  monthlyFeeCents,
  offeredPrices,
  priceFor,
  primaryButtonLabel,
  seatEstimate,
  seatLines,
} from "~/lib/billing-plan-review";

/** Plans exactly as the backend publishes them from Stripe. */
export const SCALE: PlanInfo = {
  tier: "scale",
  name: "Scale",
  description: "",
  rank: 2,
  custom: false,
  monthly_fee_cents: 250_00,
  included_seats: 15,
  included_models: 50,
  included_eval_runs: 30,
  included_credits: 10_000,
  seat_month_credits: 1500,
  managed_from_cents: 4_000_00,
  recommended_from_seats: 6,
  recommended_from_models: 200,
  prices: [
    // Stripe order is not offer order: yearly is the published term.
    { price_id: "price_scale_quarter", lookup_key: "plan_scale_quarter", amount: 900_00, currency: "usd", interval: "quarter", months: 3 },
    { price_id: "price_scale_year", lookup_key: "plan_scale_year", amount: 3_000_00, currency: "usd", interval: "year", months: 12 },
  ],
};

export const TEAM: PlanInfo = {
  ...SCALE,
  tier: "team",
  name: "Team",
  rank: 1,
  monthly_fee_cents: 100_00,
  included_seats: 5,
  included_models: 30,
  included_credits: 5_000,
  recommended_from_seats: null,
  recommended_from_models: null,
  prices: [
    { price_id: "price_team_year", lookup_key: "plan_team_year", amount: 1_200_00, currency: "usd", interval: "year", months: 12 },
    { price_id: "price_team_quarter", lookup_key: "plan_team_quarter", amount: 360_00, currency: "usd", interval: "quarter", months: 3 },
  ],
};

export const ENTERPRISE: PlanInfo = {
  ...SCALE,
  tier: "enterprise",
  name: "Enterprise",
  rank: 3,
  custom: true,
  monthly_fee_cents: null,
  included_seats: 100,
  included_models: 100,
  included_credits: 100_000,
  seat_month_credits: null,
  managed_from_cents: 8_000_00,
  recommended_from_seats: null,
  recommended_from_models: null,
  prices: [],
};

describe("billing plan review", () => {
  it("offers the terms Stripe publishes, yearly first, and prices them per month", () => {
    expect(offeredPrices(SCALE).map((p) => p.interval)).toEqual(["year", "quarter"]);
    expect(defaultPrice(SCALE)?.price_id).toBe("price_scale_year");
    expect(priceFor(SCALE, "month")).toBeNull();
    expect(monthlyEquivalentCents(priceFor(SCALE, "year")!)).toBe(250_00);
    expect(monthlyEquivalentCents(priceFor(SCALE, "quarter")!)).toBe(300_00); // 20% premium
    expect(monthlyFeeCents(SCALE)).toBe(250_00);
    expect(monthlyFeeCents({ ...TEAM, prices: [] })).toBe(100_00);
    expect(monthlyFeeCents(ENTERPRISE)).toBeNull();
    expect(defaultPrice(ENTERPRISE)).toBeNull();
    expect(feeLine(priceFor(SCALE, "year")!)).toBe("$250/mo · $3,000 billed yearly");
    expect(feeLine(priceFor(TEAM, "quarter")!)).toBe("$120/mo · $360 billed every 3 months");
    expect(
      feeLine({ price_id: "p", lookup_key: null, amount: 100_00, currency: "usd", interval: "month", months: 1 }),
    ).toBe("$100/mo, billed monthly");
  });

  it("computes added seats and their monthly credit draw from the plan's seat rate", () => {
    const scale = seatEstimate(SCALE, 12);
    expect(scale.added).toBe(0);
    expect(seatLines(scale)).toEqual(["Your organization has 12 members · 15 included · 0 added seats"]);

    const team = seatEstimate(TEAM, 7);
    expect(team.added).toBe(2);
    expect(team.creditsPerMonth).toBe(3000);
    expect(team.usdPerMonth).toBe(30);
    expect(seatLines(team)).toEqual([
      "Your organization has 7 members · 5 included · 2 added seats",
      "2 × 1,500 credits/month (≈ $30/mo) drawn from your credits",
    ]);
  });

  it("says seats are counted daily when the member count is unknown", () => {
    expect(seatLines(seatEstimate(TEAM, null))).toEqual([
      "Seats are counted daily; members beyond the 5 included use credits (1,500 credits per seat-month).",
    ]);
  });

  it("prices contracted seats in the contract, never in credits", () => {
    const est = seatEstimate(ENTERPRISE, 120);
    expect(est.added).toBe(20);
    expect(est.creditsPerMonth).toBe(0);
    expect(seatLines(est)).toEqual([
      "Your organization has 120 members · 100 included · 20 added seats",
      "Added seats are priced in your contract.",
    ]);
    expect(seatLines(seatEstimate(ENTERPRISE, null))).toEqual([
      "Seats beyond the 100 included are priced in your contract.",
    ]);
  });

  it("lists the monthly allowances in one line", () => {
    expect(includedLine(TEAM)).toBe("Included every month: 5,000 credits, 30 covered models, 30 eval runs");
    expect(includedLine(SCALE)).toBe("Included every month: 10,000 credits, 50 covered models, 30 eval runs");
  });

  it("due today is the term's fee on checkout", () => {
    const due = dueToday({ mode: "checkout", price: defaultPrice(SCALE), proration: null, loadingPreview: false, currentPeriodEnd: null });
    expect(due).toMatchObject({ kind: "flat", label: "Due today", amountCents: 3_000_00 });
    expect(primaryButtonLabel("checkout")).toBe("Continue to payment");
  });

  it("due today is the proration preview on an upgrade", () => {
    const price = defaultPrice(SCALE);
    const loading = dueToday({ mode: "upgrade", price, proration: null, loadingPreview: true, currentPeriodEnd: null });
    expect(loading.kind).toBe("loading");
    const due = dueToday({
      mode: "upgrade",
      price,
      proration: { amount_due: 150_00, currency: "usd", credit: 100_00, new_charge: 250_00, immediate: true, effective_date: null },
      loadingPreview: false,
      currentPeriodEnd: null,
    });
    expect(due).toMatchObject({ kind: "prorated", label: "Due today (prorated)", amountCents: 150_00, creditCents: 100_00 });
    expect(primaryButtonLabel("upgrade")).toBe("Confirm change");
  });

  it("a downgrade is never charged today and names the renewal date", () => {
    const price = defaultPrice(TEAM);
    const due = dueToday({ mode: "downgrade", price, proration: null, loadingPreview: false, currentPeriodEnd: "2026-10-01T12:00:00Z" });
    expect(due.kind).toBe("renewal");
    if (due.kind === "renewal") expect(due.detail).toMatch(/^changes at renewal on October 1, 2026$/);
    const withPreview = dueToday({
      mode: "downgrade",
      price,
      proration: { amount_due: 0, currency: "usd", credit: 0, new_charge: 0, immediate: false, effective_date: "2026-10-15" },
      loadingPreview: false,
      currentPeriodEnd: null,
    });
    if (withPreview.kind === "renewal") expect(withPreview.detail).toBe("changes at renewal on October 15, 2026");
  });
});
