import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PlanInfo } from "~/lib/backend-client";
import { PlanReviewDialog, type ProrationPreview } from "~/components/billing/plan-review-dialog";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

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

function q<T extends Element = HTMLElement>(container: Element, id: string): T {
  const el = container.querySelector<T>(`[data-testid="${id}"]`);
  if (!el) throw new Error(`missing ${id}`);
  return el;
}

describe("plan review dialog", () => {
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

  it("free to paid: monthly fee, seats, included, due today, continue to payment", async () => {
    const onConfirm = vi.fn();
    await act(async () =>
      root.render(
        <PlanReviewDialog
          review={{ plan: SCALE, mode: "checkout" }}
          members={12}
          rates={null}
          currentPeriodEnd={null}
          onConfirm={onConfirm}
          onCancel={() => {}}
        />,
      ),
    );
    const dialog = q(container, "plan-review-dialog");
    expect(dialog.textContent).toContain("Review your plan");
    expect(q(dialog, "review-fee").textContent).toBe("Scale · $250/mo, billed monthly");
    expect(q(dialog, "review-seats").textContent).toBe("Your organization has 12 members · 25 included · 0 added seats");
    expect(q(dialog, "review-included").textContent).toBe(
      "Included every month: 12,500 credits, 50 covered models, 30 eval runs",
    );
    expect(dialog.textContent).toContain("Beyond that, usage is paid in credits at fixed rates.");
    expect(dialog.textContent).toContain("Due today");
    expect(q(dialog, "review-due").textContent).toContain("$250");
    // Monthly only: no interval choice, no annual price anywhere.
    expect(dialog.querySelector('input[type="radio"]')).toBeNull();
    expect(dialog.textContent).not.toMatch(/annual|\$3,000|month-to-month|\+25%/i);

    const primary = q<HTMLButtonElement>(dialog, "review-primary");
    expect(primary.textContent).toBe("Continue to payment");
    await act(async () => primary.click());
    expect(onConfirm).toHaveBeenCalledWith("price_scale_month");
  });

  it("shows the added-seat credit draw when members exceed the allowance", async () => {
    await act(async () =>
      root.render(
        <PlanReviewDialog
          review={{ plan: TEAM, mode: "checkout" }}
          members={12}
          rates={null}
          currentPeriodEnd={null}
          onConfirm={() => {}}
          onCancel={() => {}}
        />,
      ),
    );
    const seats = q(container, "review-seats");
    expect(seats.textContent).toContain("Your organization has 12 members · 10 included · 2 added seats");
    expect(seats.textContent).toContain("2 × 1,000 credits/month (≈ $20/mo) drawn from your credits");
    expect(q(container, "review-due").textContent).toContain("$100");
  });

  it("says seats are counted daily when the member count is unknown", async () => {
    await act(async () =>
      root.render(
        <PlanReviewDialog
          review={{ plan: TEAM, mode: "checkout" }}
          members={null}
          rates={null}
          currentPeriodEnd={null}
          onConfirm={() => {}}
          onCancel={() => {}}
        />,
      ),
    );
    expect(q(container, "review-seats").textContent).toContain(
      "Seats are counted daily; members beyond the 10 included use credits",
    );
  });

  it("paid to paid upgrade: prorated due today from the preview, confirm change", async () => {
    const preview: ProrationPreview = {
      amount_due: 150_00,
      currency: "usd",
      credit: 100_00,
      new_charge: 250_00,
      immediate: true,
      effective_date: null,
    };
    const previewProration = vi.fn(async () => preview);
    const onConfirm = vi.fn();
    await act(async () =>
      root.render(
        <PlanReviewDialog
          review={{ plan: SCALE, mode: "upgrade" }}
          members={12}
          rates={null}
          currentPeriodEnd="2026-10-01T00:00:00Z"
          previewProration={previewProration}
          onConfirm={onConfirm}
          onCancel={() => {}}
        />,
      ),
    );
    expect(previewProration).toHaveBeenCalledWith("price_scale_month");
    const dialog = q(container, "plan-review-dialog");
    expect(dialog.textContent).toContain("Due today (prorated)");
    expect(q(dialog, "review-due").textContent).toContain("$150");
    expect(q(dialog, "review-due").textContent).toContain("$100 credit");
    const primary = q<HTMLButtonElement>(dialog, "review-primary");
    expect(primary.textContent).toBe("Confirm change");
    await act(async () => primary.click());
    expect(onConfirm).toHaveBeenCalledWith("price_scale_month");
  });

  it("downgrade: no charge today, changes at renewal", async () => {
    const previewProration = vi.fn(async () => ({
      amount_due: 0,
      currency: "usd",
      credit: 0,
      new_charge: 0,
      immediate: false,
      effective_date: "2026-10-15",
    }));
    await act(async () =>
      root.render(
        <PlanReviewDialog
          review={{ plan: TEAM, mode: "downgrade" }}
          members={12}
          rates={null}
          currentPeriodEnd={null}
          previewProration={previewProration}
          onConfirm={() => {}}
          onCancel={() => {}}
        />,
      ),
    );
    const dialog = q(container, "plan-review-dialog");
    expect(dialog.textContent).toContain("downgrade to Team");
    expect(q(dialog, "review-due").textContent).toBe("No charge today; changes at renewal on October 15, 2026");
    expect(q(dialog, "review-primary").textContent).toBe("Confirm change");
  });

  it("expands the rate table inline", async () => {
    await act(async () =>
      root.render(
        <PlanReviewDialog
          review={{ plan: TEAM, mode: "checkout" }}
          members={3}
          rates={null}
          currentPeriodEnd={null}
          onConfirm={() => {}}
          onCancel={() => {}}
        />,
      ),
    );
    expect(container.querySelector('[data-testid="review-rates"]')).toBeNull();
    await act(async () => q<HTMLButtonElement>(container, "review-rates-toggle").click());
    const rates = q(container, "review-rates");
    expect(rates.textContent).toContain("Successful thread");
    expect(rates.textContent).toContain("50 ($0.50)");
  });
});
