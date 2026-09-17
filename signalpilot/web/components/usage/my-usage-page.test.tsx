import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MyUsageResponse } from "~/lib/types";
import { MyUsagePage } from "./my-usage-page";

const mocks = vi.hoisted(() => ({
  getMyUsage: vi.fn(),
  auth: { isCloudMode: true, isLoaded: true },
  org: { membership: { role: "org:member" } as { role: string } | undefined },
}));
vi.mock("~/lib/api/usage", () => ({ getMyUsage: mocks.getMyUsage }));
vi.mock("~/lib/auth-context", () => ({ useAppAuth: () => mocks.auth }));
vi.mock("@clerk/nextjs", () => ({ useOrganization: () => mocks.org }));
// jsdom has no ResizeObserver, which recharts' ResponsiveContainer needs.
vi.mock("./daily-usage-charts", () => ({
  DailyUsageCharts: ({ daily }: { daily: unknown[] }) => <div data-testid="usage-daily-charts" data-points={daily.length} />,
}));
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
vi.mock("next/navigation", () => ({ usePathname: () => "/settings/usage/me" }));

const sample: MyUsageResponse = {
  window: { from_ts: 0, to_ts: 1, days: 30 },
  user_id: "user_a",
  totals: {
    chat_runs: 5, conversations: 2, input_tokens: 12_300, output_tokens: 800,
    cache_read_tokens: 100, cache_creation_tokens: 0, cost_usd: 0.5, queries: 40,
    blocked_queries: 1, rows_returned: 1200,
  },
  daily: [{ date: "2026-09-14", chat_runs: 5, cost_usd: 0.5, queries: 40 }],
  conversations: [
    { conversation_id: "conv-1", title: "Revenue by region", chat_runs: 3, cost_usd: 0.3, last_activity_at: 1_757_800_000 },
    { conversation_id: "conv-2", title: "", chat_runs: 2, cost_usd: 0.2, last_activity_at: 1_757_700_000 },
  ],
  connections: [
    { connection_name: "warehouse", queries: 40, rows_returned: 1200, blocked_queries: 1 },
  ],
};

describe("MyUsagePage", () => {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.org.membership = { role: "org:member" };
    mocks.getMyUsage.mockResolvedValue(sample);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => { act(() => root.unmount()); container.remove(); });
  async function render() { await act(async () => { root.render(<MyUsagePage />); }); }

  it("renders totals, conversation links, and connections; hides the members tab for members", async () => {
    await render();
    expect(mocks.getMyUsage).toHaveBeenCalledWith(30);
    const text = container.textContent ?? "";
    expect(text).toContain("$0.50");
    expect(text).toContain("12.3k");
    expect(text).toContain("warehouse");
    expect(text).toContain("untitled conversation");
    const link = container.querySelector<HTMLAnchorElement>('a[href="/chats/conv-1"]');
    expect(link?.textContent).toBe("Revenue by region");
    expect(container.querySelectorAll('[data-testid="usage-connection-row"]').length).toBe(1);
    expect(container.querySelector('a[href="/settings/usage/members"]')).toBeNull();
    expect(container.querySelector('a[href="/settings/usage/me"]')).not.toBeNull();
  });

  it("offers the members tab to admins and shows empty states", async () => {
    mocks.org.membership = { role: "org:admin" };
    mocks.getMyUsage.mockResolvedValue({ ...sample, daily: [], conversations: [], connections: [] });
    await render();
    expect(container.querySelector('a[href="/settings/usage/members"]')).not.toBeNull();
    const text = container.textContent ?? "";
    expect(text).toContain("no conversations in this period");
    expect(text).toContain("no queries in this period");
    expect(text).toContain("no activity in this period");
  });

  it("shows a neutral notice when the request fails", async () => {
    mocks.getMyUsage.mockRejectedValueOnce(new Error("500: boom"));
    await render();
    expect(container.querySelector('[data-testid="usage-error"]')?.textContent).toContain("Unable to load your usage");
  });
});
