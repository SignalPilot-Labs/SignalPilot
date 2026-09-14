import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { DailyUsageResponse, UsageSummaryResponse } from "~/lib/backend-client";
import {
  AllowanceMeter,
  ConsumptionByUnitTable,
  CreditBalanceCard,
  DailyConsumptionChart,
} from "~/components/billing/usage-panels";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// recharts' ResponsiveContainer observes its parent; jsdom has no ResizeObserver.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as typeof globalThis & { ResizeObserver?: unknown }).ResizeObserver ??=
  ResizeObserverStub;

/** `GET /api/v1/usage/summary` exactly as the backend's UsageSummaryResponse serializes. */
const SUMMARY: UsageSummaryResponse = {
  period_start: "2026-09-01",
  period_end: "2026-10-01",
  plan_tier: "team",
  is_billable: true,
  included_credits: 5_000,
  granted: 5_000,
  purchased: 0,
  consumed: 1_262,
  consumed_by_unit: {
    thread: { credits: 1_000, quantity: 20, rows: 20 },
    query: { credits: 212, quantity: 212, rows: 212 },
    model_day: { credits: 50, quantity: 2.5, rows: 3 },
    tokens: { credits: 0, quantity: 0, rows: 0 },
  },
  returned: 100,
  expired: 0,
  available: 3_838,
  overage: 0,
  overage_cents: 0,
  allowances: {
    seats: { used: 12, included: 10 },
    models: { used: 18, included: 30 },
    eval_runs: { used: 0, included: 30 },
  },
};

/** `GET /api/v1/usage/daily` in the backend's DailyUsageResponse shape. */
const DAILY: DailyUsageResponse = {
  points: [
    { date: "2026-09-01", credits: 0, by_unit: {} },
    { date: "2026-09-02", credits: 51, by_unit: { thread: 50, query: 1 } },
  ],
};

describe("usage panels on the backend response shape", () => {
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

  it("ConsumptionByUnitTable reads consumed_by_unit[unit].credits and quantity", async () => {
    await act(async () =>
      root.render(<ConsumptionByUnitTable byUnit={SUMMARY.consumed_by_unit} />),
    );
    const units = [...container.querySelectorAll("tbody tr")].map((tr) =>
      tr.getAttribute("data-testid"),
    );
    // Sorted by credits, zero-credit units dropped.
    expect(units).toEqual(["unit-thread", "unit-query", "unit-model_day"]);

    const thread = container.querySelector('[data-testid="unit-thread"]')!;
    const cells = [...thread.querySelectorAll("td")].map((td) => td.textContent);
    expect(cells).toEqual(["threads", "20", "1,000", "$10"]);

    const modelDay = container.querySelector('[data-testid="unit-model_day"]')!;
    expect(modelDay.textContent).toContain("2.5");
  });

  it("ConsumptionByUnitTable shows the empty state when nothing was consumed", async () => {
    await act(async () => root.render(<ConsumptionByUnitTable byUnit={{}} />));
    expect(container.textContent).toContain("nothing consumed yet this period");
  });

  it("CreditBalanceCard and AllowanceMeter read the summary fields", async () => {
    const granted = SUMMARY.granted + SUMMARY.purchased + SUMMARY.returned;
    await act(async () =>
      root.render(
        <>
          <CreditBalanceCard
            granted={granted}
            consumed={SUMMARY.consumed}
            available={SUMMARY.available}
            overage={SUMMARY.overage}
            periodEnd={SUMMARY.period_end}
          />
          <AllowanceMeter label="seats" use={SUMMARY.allowances.seats} beyondNote="metered daily" />
          <AllowanceMeter label="covered models" use={SUMMARY.allowances.models} beyondNote="x" />
        </>,
      ),
    );
    const balance = container.querySelector('[data-testid="credit-balance"]')!;
    expect(balance.textContent).toContain("1,262");
    expect(balance.textContent).toContain("5,100");
    expect(balance.textContent).toContain("3,838");
    expect(balance.textContent).not.toContain("overage");

    const seats = container.querySelector('[data-testid="allowance-seats"]')!;
    expect(seats.textContent).toContain("12 / 10");
    expect(seats.textContent).toContain("2 beyond allowance, metered daily");
    const models = container.querySelector('[data-testid="allowance-covered-models"]')!;
    expect(models.textContent).toContain("within allowance");
  });

  it("DailyConsumptionChart reads credits per point and renders the empty state without data", async () => {
    await act(async () =>
      root.render(<DailyConsumptionChart points={[DAILY.points[0]]} />),
    );
    expect(container.textContent).toContain("no consumption yet this period");

    await act(async () => root.render(<DailyConsumptionChart points={DAILY.points} />));
    expect(container.textContent).not.toContain("no consumption yet this period");
  });
});
