import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PlanInfo } from "~/lib/backend-client";
import { PlanCard } from "~/components/billing/plan-card";
import { EnterpriseCard } from "~/components/billing/enterprise-card";
import { PlanGrid } from "~/components/billing/plan-grid";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const TEAM: PlanInfo = {
  tier: "team",
  name: "Team",
  description: "for one data team",
  monthly_fee_cents: 100_00,
  included_seats: 10,
  included_models: 30,
  included_eval_runs: 30,
  included_credits: 5_000,
  seat_month_credits: 1000,
  managed_from_cents: 1_500_00,
  prices: [{ price_id: "price_team_month", lookup_key: "plan_team_month", amount: 100_00, currency: "usd", interval: "month" }],
};

const SCALE: PlanInfo = {
  ...TEAM,
  tier: "scale",
  name: "Scale",
  monthly_fee_cents: 250_00,
  included_seats: 25,
  included_models: 50,
  included_credits: 12_500,
  prices: [
    // A stale annual price the API may still return; it must be ignored.
    { price_id: "price_scale_year", lookup_key: "plan_scale_year", amount: 3_000_00, currency: "usd", interval: "year" },
    { price_id: "price_scale_month", lookup_key: "plan_scale_month", amount: 250_00, currency: "usd", interval: "month" },
  ],
};

const ENTERPRISE: PlanInfo = {
  ...TEAM,
  tier: "enterprise",
  name: "Enterprise",
  monthly_fee_cents: 1_500_00,
  included_seats: 100,
  included_models: 100,
  included_credits: 75_000,
  seat_month_credits: 1500,
  prices: [],
};

describe("plan cards", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("shows the monthly price, the allowances and no interval toggle", async () => {
    await act(async () =>
      root.render(
        <PlanGrid plans={[TEAM, SCALE, ENTERPRISE]} currentTier="free" onSelect={() => {}} />,
      ),
    );
    const team = container.querySelector('[data-testid="plan-card-team"]')!;
    const scale = container.querySelector('[data-testid="plan-card-scale"]')!;
    expect(team.querySelector('[data-testid="plan-price"]')?.textContent).toBe("$100");
    expect(scale.querySelector('[data-testid="plan-price"]')?.textContent).toBe("$250");
    expect(scale.textContent).toContain("25 seats");
    expect(scale.textContent).toContain("50 covered models");
    expect(scale.textContent).toContain("30 eval runs per month");
    expect(scale.textContent).toContain("12,500 credits per month");
    expect(scale.textContent).toContain("billed monthly");
    // Monthly only: no toggle, no annual price, no premium anywhere in the row.
    expect(container.textContent).not.toMatch(/annual|month-to-month|\+25%|\$3,000/i);
    expect(container.querySelectorAll("button").length).toBe(2);
    expect(container.querySelector('[data-testid="plan-card-enterprise"] [data-testid="plan-price"]')?.textContent).toBe(
      "from $1,500",
    );
  });

  it("marks the current plan and labels higher and lower tiers", async () => {
    const onSelect = vi.fn();
    await act(async () =>
      root.render(<PlanGrid plans={[TEAM, SCALE, ENTERPRISE]} currentTier="scale" onSelect={onSelect} />),
    );
    const scale = container.querySelector('[data-testid="plan-card-scale"]')!;
    expect(scale.querySelector('[data-testid="plan-current"]')?.textContent).toContain("Current plan");
    expect(scale.querySelector('[data-testid="plan-select"]')).toBeNull();
    const teamButton = container.querySelector<HTMLButtonElement>('[data-testid="plan-card-team"] [data-testid="plan-select"]')!;
    expect(teamButton.textContent).toContain("Downgrade");
    await act(async () => teamButton.click());
    expect(onSelect).toHaveBeenCalledWith(TEAM);

    await act(async () =>
      root.render(<PlanGrid plans={[TEAM, SCALE, ENTERPRISE]} currentTier="team" onSelect={onSelect} />),
    );
    expect(
      container.querySelector('[data-testid="plan-card-scale"] [data-testid="plan-select"]')?.textContent,
    ).toContain("Upgrade");
  });

  it("keeps the pending-downgrade state on the target card", async () => {
    await act(async () =>
      root.render(
        <PlanCard
          plan={TEAM}
          currentTier="scale"
          pendingDowngradeTo="team"
          pendingDowngradeDate="2026-10-01"
          onSelect={() => {}}
        />,
      ),
    );
    expect(container.textContent).toContain("Active Oct 1");
    expect(container.querySelector('[data-testid="plan-select"]')).toBeNull();
  });

  it("enterprise card has no buy button, only Contact us", async () => {
    await act(async () => root.render(<EnterpriseCard plan={ENTERPRISE} isCurrent={false} />));
    expect(container.querySelector("button")).toBeNull();
    const contact = container.querySelector<HTMLAnchorElement>('[data-testid="enterprise-contact"]')!;
    expect(contact.textContent).toContain("Contact us");
    expect(contact.getAttribute("href")).toMatch(/^mailto:/);
    expect(container.textContent).toContain("Priced to your estate, one purchase order");
    expect(container.textContent).toContain("from $1,500");
  });

  it("an enterprise org sees only the enterprise card", async () => {
    await act(async () =>
      root.render(<PlanGrid plans={[TEAM, SCALE, ENTERPRISE]} currentTier="enterprise" onSelect={() => {}} />),
    );
    expect(container.querySelector('[data-testid="plan-card-team"]')).toBeNull();
    expect(container.querySelector('[data-testid="plan-card-scale"]')).toBeNull();
    const card = container.querySelector('[data-testid="plan-card-enterprise"]')!;
    expect(card.querySelector('[data-testid="plan-current"]')?.textContent).toContain("Current plan");
    expect(card.querySelector('[data-testid="enterprise-contact"]')?.textContent).toContain("Contact us for changes");
    expect(card.querySelector("button")).toBeNull();
  });
});
