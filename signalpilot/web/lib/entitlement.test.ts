import { describe, expect, it } from "vitest";

import {
  FREE_ENTITLEMENT,
  LOCAL_ENTITLEMENT,
  TIER_RANK,
  entitlementFromPayload,
  entitlementFromSubscription,
  isBillableRow,
  normalizeTier,
  tierLabel,
} from "~/lib/entitlement";

const NOW = new Date("2026-09-14T12:00:00Z");

describe("isBillableRow", () => {
  it("is billable for active and trialing paid tiers", () => {
    expect(isBillableRow({ plan_tier: "team", status: "active" }, NOW)).toBe(true);
    expect(isBillableRow({ plan_tier: "scale", status: "trialing" }, NOW)).toBe(true);
    expect(isBillableRow({ plan_tier: "enterprise", status: "active" }, NOW)).toBe(true);
  });

  it("is never billable on the free tier, whatever the status", () => {
    expect(isBillableRow({ plan_tier: "free", status: "active" }, NOW)).toBe(false);
    expect(isBillableRow({ plan_tier: "free", status: "trialing" }, NOW)).toBe(false);
  });

  it("keeps past_due orgs billable only inside the grace window", () => {
    const row = { plan_tier: "team", status: "past_due" };
    expect(isBillableRow({ ...row, grace_until: "2026-09-28T00:00:00Z" }, NOW)).toBe(true);
    expect(isBillableRow({ ...row, grace_until: "2026-09-01T00:00:00Z" }, NOW)).toBe(false);
    expect(isBillableRow({ ...row, grace_until: null }, NOW)).toBe(false);
    expect(isBillableRow({ ...row, grace_until: "not a date" }, NOW)).toBe(false);
  });

  it("is not billable once canceled or unpaid", () => {
    expect(isBillableRow({ plan_tier: "team", status: "canceled" }, NOW)).toBe(false);
    expect(isBillableRow({ plan_tier: "scale", status: "unpaid" }, NOW)).toBe(false);
  });

  it("trusts an explicit is_billable from the backend", () => {
    expect(isBillableRow({ plan_tier: "team", status: "canceled", is_billable: true }, NOW)).toBe(true);
    expect(isBillableRow({ plan_tier: "team", status: "active", is_billable: false }, NOW)).toBe(false);
  });
});

describe("normalizeTier", () => {
  it("accepts the five known tiers and maps anything else to free", () => {
    expect(normalizeTier("team")).toBe("team");
    expect(normalizeTier("scale")).toBe("scale");
    expect(normalizeTier("enterprise")).toBe("enterprise");
    expect(normalizeTier("unlimited")).toBe("unlimited");
    expect(normalizeTier("free")).toBe("free");
    // Legacy names from the old billing model never leak into the UI.
    expect(normalizeTier("pro")).toBe("free");
    expect(normalizeTier(undefined)).toBe("free");
  });

  it("ranks tiers in plan order", () => {
    expect(TIER_RANK.free).toBeLessThan(TIER_RANK.team);
    expect(TIER_RANK.team).toBeLessThan(TIER_RANK.scale);
    expect(TIER_RANK.scale).toBeLessThan(TIER_RANK.enterprise);
  });

  it("labels tiers for display", () => {
    expect(tierLabel("scale")).toBe("Scale");
    expect(tierLabel("free")).toBe("Free");
  });
});

describe("entitlementFromSubscription", () => {
  it("maps the backend row into the entitlement the UI gates on", () => {
    const e = entitlementFromSubscription(
      {
        plan_tier: "scale",
        status: "active",
        included_seats: 25,
        included_models: 50,
        included_eval_runs: 30,
        included_credits: 12_500,
        managed: true,
        billing_interval: "year",
        enterprise_flags: { sso: true },
      },
      NOW,
    );
    expect(e).toEqual({
      tier: "scale",
      isBillable: true,
      includedSeats: 25,
      includedModels: 50,
      includedEvalRuns: 30,
      includedCredits: 12_500,
      managed: true,
      billingInterval: "year",
      enterpriseFlags: { sso: true },
    });
  });

  it("defaults every allowance to zero for a free row", () => {
    const e = entitlementFromSubscription({ plan_tier: "free", status: "active" }, NOW);
    expect(e).toEqual(FREE_ENTITLEMENT);
  });
});

describe("entitlementFromPayload", () => {
  it("maps the gateway bootstrap entitlement", () => {
    const e = entitlementFromPayload({
      tier: "team",
      is_billable: true,
      included_seats: 10,
      included_models: 30,
      included_eval_runs: 30,
      included_credits: 5_000,
      managed: false,
      enterprise_flags: null,
    });
    expect(e.tier).toBe("team");
    expect(e.isBillable).toBe(true);
    expect(e.includedCredits).toBe(5_000);
    expect(e.enterpriseFlags).toEqual({});
    expect(e.billingInterval).toBe("month");
  });
});

describe("local mode", () => {
  it("is unlimited and billable", () => {
    expect(LOCAL_ENTITLEMENT.tier).toBe("unlimited");
    expect(LOCAL_ENTITLEMENT.isBillable).toBe(true);
  });
});
