import { describe, expect, it } from "vitest";

import type { PlanInfo } from "~/lib/backend-client";
import {
  dueToday,
  feeLine,
  includedLine,
  monthlyFeeCents,
  monthlyPrice,
  primaryButtonLabel,
  seatEstimate,
  seatLines,
} from "~/lib/billing-plan-review";

const SCALE: PlanInfo = {
  tier: "scale",
  name: "Scale",
  description: "",
  monthly_fee_cents: 250_00,
  included_seats: 25,
  included_models: 50,
  included_eval_runs: 30,
  included_credits: 12_500,
  seat_month_credits: 1000,
  managed_from_cents: 2_500_00,
  prices: [
    // A stale annual price the API may still return; it must be ignored.
    { price_id: "price_scale_year", lookup_key: "plan_scale_year", amount: 3_000_00, currency: "usd", interval: "year" },
    { price_id: "price_scale_month", lookup_key: "plan_scale_month", amount: 250_00, currency: "usd", interval: "month" },
  ],
};

const TEAM: PlanInfo = {
  ...SCALE,
  tier: "team",
  name: "Team",
  monthly_fee_cents: 100_00,
  included_seats: 10,
  included_models: 30,
  included_credits: 5_000,
  prices: [{ price_id: "price_team_month", lookup_key: "plan_team_month", amount: 100_00, currency: "usd", interval: "month" }],
};

describe("billing plan review", () => {
  it("picks the monthly price and ignores any other interval", () => {
    expect(monthlyPrice(SCALE)?.price_id).toBe("price_scale_month");
    expect(monthlyFeeCents(SCALE)).toBe(250_00);
    expect(monthlyPrice({ prices: SCALE.prices.filter((p) => p.interval === "year") })).toBeNull();
    expect(monthlyFeeCents({ ...TEAM, prices: [] })).toBe(100_00);
    expect(feeLine(SCALE)).toBe("$250/mo, billed monthly");
    expect(feeLine(TEAM)).toBe("$100/mo, billed monthly");
  });

  it("computes added seats and their monthly credit draw", () => {
    const scale = seatEstimate(SCALE, 12);
    expect(scale.added).toBe(0);
    expect(seatLines(scale)).toEqual(["Your organization has 12 members · 25 included · 0 added seats"]);

    const team = seatEstimate(TEAM, 12);
    expect(team.added).toBe(2);
    expect(team.creditsPerMonth).toBe(2000);
    expect(team.usdPerMonth).toBe(20);
    expect(seatLines(team)).toEqual([
      "Your organization has 12 members · 10 included · 2 added seats",
      "2 × 1,000 credits/month (≈ $20/mo) drawn from your credits",
    ]);
  });

  it("says seats are counted daily when the member count is unknown", () => {
    expect(seatLines(seatEstimate(TEAM, null))).toEqual([
      "Seats are counted daily; members beyond the 10 included use credits (1,000 credits per seat-month).",
    ]);
  });

  it("lists the monthly allowances in one line", () => {
    expect(includedLine(TEAM)).toBe("Included every month: 5,000 credits, 30 covered models, 30 eval runs");
    expect(includedLine(SCALE)).toBe("Included every month: 12,500 credits, 50 covered models, 30 eval runs");
  });

  it("due today is the monthly fee on checkout", () => {
    const due = dueToday({ mode: "checkout", price: monthlyPrice(SCALE), proration: null, loadingPreview: false, currentPeriodEnd: null });
    expect(due).toMatchObject({ kind: "flat", label: "Due today", amountCents: 250_00 });
    expect(primaryButtonLabel("checkout")).toBe("Continue to payment");
  });

  it("due today is the proration preview on an upgrade", () => {
    const price = monthlyPrice(SCALE);
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
    const price = monthlyPrice(TEAM);
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
