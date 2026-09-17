import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OrgUsageResponse } from "~/lib/types";
import { ApiRequestError } from "~/lib/api/client";
import { MembersUsagePage } from "./members-usage-page";

const mocks = vi.hoisted(() => ({
  getOrgUsage: vi.fn(),
  auth: { isCloudMode: true, isLoaded: true },
  org: { membership: { role: "org:admin" } as { role: string } | undefined, memberships: { data: [] as unknown[] } },
}));
vi.mock("~/lib/api/usage", () => ({ getOrgUsage: mocks.getOrgUsage }));
vi.mock("~/lib/auth-context", () => ({ useAppAuth: () => mocks.auth }));
vi.mock("@clerk/nextjs", () => ({ useOrganization: () => mocks.org }));
// jsdom has no ResizeObserver, which recharts' ResponsiveContainer needs.
vi.mock("./daily-usage-charts", () => ({
  DailyUsageCharts: ({ daily }: { daily: unknown[] }) => <div data-testid="usage-daily-charts" data-points={daily.length} />,
}));
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
vi.mock("next/navigation", () => ({ usePathname: () => "/settings/usage/members" }));

const totals = {
  chat_runs: 42, conversations: 7, input_tokens: 1_234_000, output_tokens: 56_700,
  cache_read_tokens: 0, cache_creation_tokens: 0, cost_usd: 12.345, queries: 300,
  blocked_queries: 2, rows_returned: 9000, eval_runs: null, last_active_at: null,
};
const sample: OrgUsageResponse = {
  window: { from_ts: 0, to_ts: 1, days: 30 },
  totals,
  members: [
    { ...totals, user_id: "user_a", chat_runs: 30, cost_usd: 10 },
    { ...totals, user_id: "user_b", chat_runs: 12, cost_usd: 2.345 },
  ],
  daily: [{ date: "2026-09-14", chat_runs: 3, cost_usd: 1.5, queries: 10 }],
};

describe("MembersUsagePage", () => {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.auth.isCloudMode = true;
    mocks.org.membership = { role: "org:admin" };
    mocks.org.memberships.data = [
      { publicUserData: { userId: "user_a", firstName: "Ada", lastName: "Lovelace", identifier: "ada@example.com" } },
    ];
    mocks.getOrgUsage.mockResolvedValue(sample);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => { act(() => root.unmount()); container.remove(); });
  async function render() { await act(async () => { root.render(<MembersUsagePage />); }); }

  it("renders totals, resolved member names, and a members tab for admins", async () => {
    await render();
    expect(mocks.getOrgUsage).toHaveBeenCalledWith(30);
    const text = container.textContent ?? "";
    expect(text).toContain("$12.35");
    expect(text).toContain("1.2M");
    expect(text).toContain("56.7k");
    expect(text).toContain("Ada Lovelace");
    expect(text).toContain("ada@example.com");
    expect(text).toContain("user_b");
    expect(container.querySelectorAll('[data-testid="usage-member-row"]').length).toBe(2);
    expect(text).toContain("Members");
    expect(container.querySelector('[data-testid="usage-daily-charts"]')?.getAttribute("data-points")).toBe("1");
    expect(container.querySelector('[class*="color-error"]')).toBeNull();
  });

  it("changes the period and re-sorts by runs", async () => {
    await render();
    await act(async () => { container.querySelector<HTMLButtonElement>('[data-testid="usage-period-7"]')!.click(); });
    expect(mocks.getOrgUsage).toHaveBeenLastCalledWith(7);
    const runsHeader = Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.startsWith("runs"))!;
    await act(async () => { runsHeader.click(); });
    expect(runsHeader.getAttribute("aria-sort")).toBe("descending");
  });

  it("shows the admins-only notice for members and on a 403", async () => {
    mocks.org.membership = { role: "org:member" };
    await render();
    expect(container.querySelector('[data-testid="usage-admins-only"]')).not.toBeNull();
    expect(mocks.getOrgUsage).not.toHaveBeenCalled();

    mocks.org.membership = { role: "org:admin" };
    mocks.getOrgUsage.mockRejectedValueOnce(new ApiRequestError(403, "forbidden"));
    await render();
    expect(container.querySelector('[data-testid="usage-admins-only"]')).not.toBeNull();
  });
});
