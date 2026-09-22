import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DailyUsageResponse,
  UsageByUserResponse,
  UsageSummaryResponse,
} from "~/lib/backend-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as typeof globalThis & { ResizeObserver?: unknown }).ResizeObserver ??=
  ResizeObserverStub;

const SUMMARY: UsageSummaryResponse = {
  period_start: "2026-09-01",
  period_end: "2026-10-01",
  plan_tier: "team",
  is_billable: true,
  included_credits: 5_000,
  granted: 5_000,
  purchased: 0,
  consumed: 1_262,
  consumed_by_unit: { thread: { credits: 1_000, quantity: 20, rows: 20 } },
  returned: 0,
  expired: 0,
  available: 3_738,
  overage: 0,
  overage_cents: 0,
  allowances: {
    seats: { used: 3, included: 10 },
    models: { used: 4, included: 30 },
    eval_runs: { used: 0, included: 30 },
  },
};

const DAILY: DailyUsageResponse = { points: [{ date: "2026-09-01", credits: 12, by_unit: {} }] };

const BY_USER: UsageByUserResponse = {
  period_start: "2026-09-01",
  period_end: "2026-10-01",
  rows: [
    {
      user_id: "user_1",
      name: "Ada Lovelace",
      email: "ada@example.com",
      credits_consumed: -900,
      threads: 12,
      queries: 140,
      tokens_in: 250_000,
      tokens_out: 40_000,
      tokens_cache_read: 90_000,
      token_credits: -30,
    },
    {
      user_id: null,
      name: null,
      email: null,
      credits_consumed: -50,
      threads: 0,
      queries: 0,
      tokens_in: 0,
      tokens_out: 0,
      tokens_cache_read: 0,
      token_credits: 0,
    },
  ],
};

const client = vi.hoisted(() => ({
  getUsageSummary: vi.fn(),
  getUsageDaily: vi.fn(),
  getUsageByUser: vi.fn(),
  getPlans: vi.fn(),
}));

vi.mock("next/navigation", () => ({ usePathname: () => "/settings/usage" }));

vi.mock("~/lib/backend-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("~/lib/backend-client")>();
  return { ...actual, useBackendClient: () => client };
});

import { OrgUsageContent } from "~/components/billing/usage-page-content";

async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

describe("usage page content", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    client.getUsageSummary.mockReset().mockResolvedValue(SUMMARY);
    client.getUsageDaily.mockReset().mockResolvedValue(DAILY);
    client.getUsageByUser.mockReset().mockResolvedValue(BY_USER);
    client.getPlans.mockReset().mockResolvedValue({
      plans: [],
      publishable_key: "",
      rates: {
        credit_cents: 1, thread_credits: 50, query_credits: 1, model_month_credits: 600,
        eval_run_credits: 50, token_credits_per_dollar: 100, overage_cents_per_credit: 1, version: "2",
      },
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("admin view shows org totals and the per-user table", async () => {
    await act(async () => root.render(<OrgUsageContent />));
    await flush();
    expect(container.querySelector('[data-testid="org-usage"]')).not.toBeNull();
    expect(container.textContent).toContain("allowances");
    const table = container.querySelector('[data-testid="usage-by-user-table"]');
    expect(table).not.toBeNull();
    expect(container.querySelector('[data-testid="usage-user-user_1"]')?.textContent).toContain("Ada Lovelace");
    expect(container.querySelector('[data-testid="usage-user-user_1"]')?.textContent).toContain("ada@example.com");
    expect(container.querySelector('[data-testid="usage-user-system"]')?.textContent).toContain("System / scheduled");
    // Highest consumer first.
    const rows = Array.from(container.querySelectorAll('[data-testid^="usage-user-"]'));
    expect(rows[0].getAttribute("data-testid")).toBe("usage-user-user_1");
    expect(client.getUsageByUser).toHaveBeenCalledTimes(1);
    expect(client.getUsageByUser.mock.calls[0][0]).toMatch(/^\d{4}-\d{2}-01$/);
  });

  it("admin period selector refetches by-user rows", async () => {
    await act(async () => root.render(<OrgUsageContent />));
    await flush();
    const select = container.querySelector<HTMLSelectElement>('select[aria-label="billing period"]');
    expect(select).not.toBeNull();
    const second = select!.options[1].value;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
      setter?.call(select, second);
      select!.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await flush();
    expect(client.getUsageByUser).toHaveBeenLastCalledWith(second);
  });

  it("admin view links the sibling usage tabs it is given", async () => {
    await act(async () =>
      root.render(<OrgUsageContent tabs={[{ label: "My usage", href: "/settings/usage/me" }]} />),
    );
    await flush();
    expect(container.querySelector('a[href="/settings/usage/me"]')).not.toBeNull();
  });

  it("admin view reads extra usage as neutral extra cost, never the error token", async () => {
    client.getUsageSummary.mockResolvedValue({
      ...SUMMARY,
      consumed: 5_400,
      available: -400,
      overage: 400,
      overage_cents: 400,
    });
    await act(async () => root.render(<OrgUsageContent />));
    await flush();
    const balance = container.querySelector('[data-testid="credit-balance"]')!;
    expect(balance.querySelector('[data-testid="usage-extra"]')?.textContent).toContain("400");
    expect(balance.querySelector('[data-testid="usage-included-copy"]')).not.toBeNull();
    expect(balance.querySelector('[class*="color-error"]')).toBeNull();
    expect(container.textContent).not.toContain("overage");
  });
});
