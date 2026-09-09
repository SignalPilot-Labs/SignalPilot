import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DashboardListResult, RunStep } from "~/lib/chat-run-steps";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { ToolCard } from "../tool-card";
import { dashboardFreshness, summarizeDashboardList } from "./dashboard-list-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = Date.parse("2026-09-08T12:00:00Z");

const list = (overrides: Partial<DashboardListResult> = {}): DashboardListResult => ({
  kind: "dashboard_list",
  summary: "2 dashboards",
  resultText: "{}",
  resultChars: 2,
  truncated: false,
  errorMessage: null,
  total: 2,
  dashboardsTruncated: false,
  dashboards: [
    {
      id: "dash_1",
      slug: "revenue",
      name: "Revenue overview",
      description: "Monthly revenue by region.",
      chartCount: 9,
      visibility: "org",
      updatedAt: "2026-09-08T09:00:00Z",
      lastRefreshAt: "2026-09-08T09:00:00Z",
      canEdit: true,
    },
    {
      id: "dash_2",
      slug: "pipeline",
      name: "Pipeline health",
      description: null,
      chartCount: 1,
      visibility: "private",
      updatedAt: "2026-09-06T12:00:00Z",
      lastRefreshAt: null,
      canEdit: false,
    },
  ],
  ...overrides,
});

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "l1",
    sequence: 40,
    category: "notebook",
    status: "succeeded",
    title: "Listing dashboards",
    tool: "dashboard_list_published",
    toolOrigin: "chat",
    input: { limit: 20 },
    sql: null,
    code: null,
    file: null,
    sources: [],
    detail: null,
    result: null,
    startedAt: "2026-09-01T12:00:00.000Z",
    endedAt: "2026-09-01T12:00:00.400Z",
    durationMs: 400,
    children: [],
    subagentType: null,
    report: null,
    liveText: "",
    ...overrides,
  };
}

const q = (root: ParentNode, selector: string) => root.querySelector(selector);

describe("summarizeDashboardList", () => {
  it("counts the dashboards", () => {
    expect(summarizeDashboardList(step({ result: list() }))).toEqual({
      title: "Published dashboards",
      stat: "2 dashboards",
      ok: true,
    });
    expect(summarizeDashboardList(step({ result: list({ total: 1, dashboards: [] }) })).stat).toBe(
      "1 dashboard",
    );
  });
  it("has no stat without a result and is not ok when failed", () => {
    expect(summarizeDashboardList(step())).toEqual({
      title: "Published dashboards",
      stat: null,
      ok: true,
    });
    expect(summarizeDashboardList(step({ status: "failed" })).ok).toBe(false);
  });
});

describe("dashboardFreshness", () => {
  it("prefers the last refresh and falls back to the last edit", () => {
    expect(dashboardFreshness({ lastRefreshAt: "2026-09-08T09:00:00Z", updatedAt: null }, NOW)).toBe(
      "refreshed 3 h ago",
    );
    expect(dashboardFreshness({ lastRefreshAt: null, updatedAt: "2026-09-06T12:00:00Z" }, NOW)).toBe(
      "updated 2 d ago",
    );
    expect(dashboardFreshness({ lastRefreshAt: null, updatedAt: null }, NOW)).toBeNull();
  });
});

describe("dashboard list card", () => {
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
  const render = async (s: RunStep) => {
    await act(async () => {
      root.render(
        <ol>
          <ToolCard step={s} groupLive isLastInGroup />
        </ol>,
      );
    });
  };

  it("shows the input pills and a progress rail while running", async () => {
    await render(step({ status: "running", endedAt: null, durationMs: null }));
    const body = q(container, '[data-testid="chat-dashboard-list-card"]');
    expect(body?.textContent).toContain("20");
    expect(body?.textContent).toContain("Listing dashboards…");
  });

  it("expands to one row per dashboard with chart count, visibility, freshness and Open", async () => {
    await render(step({ result: list() }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("2 dashboards");
    await act(async () => chip.click());
    const rows = container.querySelectorAll('[data-testid="chat-dashboard-list-entry"]');
    expect(rows.length).toBe(2);
    expect(rows[0].getAttribute("data-slug")).toBe("revenue");
    expect(rows[0].getAttribute("data-can-edit")).toBe("1");
    expect(rows[0].textContent).toContain("Revenue overview");
    expect(rows[0].textContent).toContain("9 charts");
    expect(rows[0].textContent).toContain("Monthly revenue by region.");
    expect(rows[0].textContent).toMatch(/refreshed .* ago/);
    expect(q(rows[0], '[data-testid="chat-dashboard-list-visibility"]')?.textContent).toBe("org");
    expect(q(rows[0], '[data-testid="chat-dashboard-list-open"]')?.getAttribute("href")).toBe(
      "/dashboards/revenue",
    );
    expect(rows[1].textContent).toContain("1 chart");
    expect(rows[1].textContent).toMatch(/updated /);
    expect(rows[1].getAttribute("data-can-edit")).toBe("0");
  });

  it("says when the gallery is empty", async () => {
    await render(step({ result: list({ total: 0, dashboards: [] }) }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("0 dashboards");
    await act(async () => chip.click());
    expect(container.textContent).toContain("No dashboards have been published yet.");
  });

  it("says how many entries the projector left out", async () => {
    await render(step({ result: list({ total: 5 }) }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("5 dashboards");
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-dashboard-list-truncated"]')?.textContent).toBe("3 more not shown");
  });

  it("says the list was capped when only the flag is known", async () => {
    await render(step({ result: list({ dashboardsTruncated: true }) }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-dashboard-list-truncated"]')?.textContent).toBe(
      "More dashboards not shown",
    );
  });
});
