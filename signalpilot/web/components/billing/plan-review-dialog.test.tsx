import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlanReviewDialog, type ProrationPreview } from "~/components/billing/plan-review-dialog";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

import { LIVE_RATES } from "~/lib/billing-rates.test";
import { SCALE, TEAM } from "~/lib/billing-plan-review.test";

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

  it("free to paid: yearly term by default, seats, included, due today, continue to payment", async () => {
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
    expect(q(dialog, "review-fee").textContent).toBe("Scale · $250/mo · $3,000 billed yearly");
    expect(q(dialog, "review-seats").textContent).toBe("Your organization has 12 members · 15 included · 0 added seats");
    expect(q(dialog, "review-included").textContent).toBe(
      "Included every month: 10,000 credits, 50 covered models, 30 eval runs",
    );
    expect(dialog.textContent).toContain("Beyond that, usage is paid in credits at fixed rates.");
    expect(dialog.textContent).toContain("Due today");
    expect(q(dialog, "review-due").textContent).toContain("$3,000");
    // The terms Stripe offers, yearly selected.
    expect(q(dialog, "review-term-year").getAttribute("aria-checked")).toBe("true");
    expect(q(dialog, "review-term-quarter").getAttribute("aria-checked")).toBe("false");

    const primary = q<HTMLButtonElement>(dialog, "review-primary");
    expect(primary.textContent).toBe("Continue to payment");
    await act(async () => primary.click());
    expect(onConfirm).toHaveBeenCalledWith("price_scale_year");
  });

  it("switching to the 3-month term changes the fee, due today and the price bought", async () => {
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
    await act(async () => q<HTMLButtonElement>(container, "review-term-quarter").click());
    expect(q(container, "review-fee").textContent).toBe("Scale · $300/mo · $900 billed every 3 months");
    expect(q(container, "review-due").textContent).toContain("$900");
    await act(async () => q<HTMLButtonElement>(container, "review-primary").click());
    expect(onConfirm).toHaveBeenCalledWith("price_scale_quarter");
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
    expect(seats.textContent).toContain("Your organization has 12 members · 5 included · 7 added seats");
    expect(seats.textContent).toContain("7 × 1,500 credits/month (≈ $105/mo) drawn from your credits");
    expect(q(container, "review-due").textContent).toContain("$1,200");
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
      "Seats are counted daily; members beyond the 5 included use credits",
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
    expect(previewProration).toHaveBeenCalledWith("price_scale_year");
    const dialog = q(container, "plan-review-dialog");
    expect(dialog.textContent).toContain("Due today (prorated)");
    expect(q(dialog, "review-due").textContent).toContain("$150");
    expect(q(dialog, "review-due").textContent).toContain("$100 credit");
    const primary = q<HTMLButtonElement>(dialog, "review-primary");
    expect(primary.textContent).toBe("Confirm change");
    await act(async () => primary.click());
    expect(onConfirm).toHaveBeenCalledWith("price_scale_year");
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

  it("expands the rate table inline from the live card, with the plan's seat rate", async () => {
    await act(async () =>
      root.render(
        <PlanReviewDialog
          review={{ plan: TEAM, mode: "checkout" }}
          members={3}
          rates={LIVE_RATES}
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
    expect(rates.textContent).toContain("1,500 ($15)");
  });

  it("waits for the rate card instead of showing guessed rates", async () => {
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
    expect(container.querySelector('[data-testid="review-rates-toggle"]')).toBeNull();
    expect(container.textContent).toContain("loading rates...");
  });
});
