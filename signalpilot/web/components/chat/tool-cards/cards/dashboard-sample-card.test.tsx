import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { DashboardSampleResult, RunStep } from "~/lib/chat-run-steps";
import { ToolCard } from "../tool-card";
import { summarizeDashboardSample } from "./dashboard-sample-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const LEGACY = {
  kind: "legacy",
  summary: null,
  resultText: null,
  resultChars: null,
  truncated: false,
  errorMessage: null,
} as const;

const sample = (overrides: Partial<DashboardSampleResult> = {}): DashboardSampleResult => ({
  kind: "dashboard_sample",
  summary: "2 charts checked, 1 issue",
  resultText: "{}",
  resultChars: 2,
  truncated: false,
  errorMessage: null,
  dashboardValid: true,
  errors: [],
  charts: [
    {
      id: "revenue_trend",
      type: "line",
      dataset: "revenue_monthly",
      rowCount: 48,
      issueCount: 0,
      columns: [
        { name: "month", inferredType: "date" },
        { name: "region", inferredType: "string" },
        { name: "revenue", inferredType: "number" },
      ],
      rows: [
        { month: "2024-01-01", region: "North", revenue: 120000 },
        { month: "2024-01-01", region: "South", revenue: 102125 },
      ],
      issues: [],
    },
    {
      id: "region_share",
      type: "pie",
      dataset: "revenue_by_region",
      rowCount: 4,
      issueCount: 1,
      columns: [{ name: "region", inferredType: "string" }],
      rows: [{ region: "North" }],
      issues: [
        {
          code: "missing_column",
          message: 'Chart "region_share": column "revenue" is missing. Available: region.',
        },
      ],
    },
  ],
  ...overrides,
});

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "d1",
    sequence: 40,
    category: "artifact",
    status: "succeeded",
    title: "Checking dashboard data",
    tool: "dashboard_sample_data",
    toolOrigin: "chat",
    input: { path: "artifacts/revenue.dashboard.json", chart_ids: ["revenue_trend", "region_share"] },
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

describe("summarizeDashboardSample", () => {
  it("counts charts and issues", () => {
    expect(summarizeDashboardSample(step({ result: sample() }))).toEqual({
      title: "Dashboard data check",
      stat: "2 charts checked, 1 issue",
      ok: true,
    });
  });
  it("has no stat without a result and is not ok when failed or invalid", () => {
    expect(summarizeDashboardSample(step())).toEqual({
      title: "Dashboard data check",
      stat: null,
      ok: true,
    });
    expect(summarizeDashboardSample(step({ status: "failed" })).ok).toBe(false);
    expect(
      summarizeDashboardSample(
        step({ result: sample({ dashboardValid: false, charts: [], errors: ["/title: required"] }) }),
      ),
    ).toEqual({ title: "Dashboard data check", stat: "invalid dashboard spec", ok: false });
  });
});

describe("dashboard sample card", () => {
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
    const body = q(container, '[data-testid="chat-dashboard-sample-card"]');
    expect(body?.textContent).toContain("revenue.dashboard.json");
    expect(body?.textContent).toContain("Checking dashboard data…");
  });

  it("expands to one row per chart with issues and sample rows", async () => {
    await render(step({ result: sample() }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("2 charts checked, 1 issue");
    await act(async () => chip.click());
    const charts = container.querySelectorAll('[data-testid="chat-dashboard-sample-chart"]');
    expect(charts.length).toBe(2);
    expect(charts[0].getAttribute("data-chart-id")).toBe("revenue_trend");
    expect(charts[0].textContent).toContain("line");
    expect(charts[0].textContent).toContain("48 rows");
    expect(charts[0].textContent).toContain("month · region · revenue");
    expect(charts[0].querySelector('[data-testid="chat-data-table"]')).not.toBeNull();
    expect(charts[0].textContent).toContain("102125");
    expect(charts[0].querySelectorAll('[data-testid="chat-dashboard-sample-issue"]').length).toBe(0);
    const issues = charts[1].querySelectorAll('[data-testid="chat-dashboard-sample-issue"]');
    expect(issues.length).toBe(1);
    expect(issues[0].textContent).toContain("missing_column");
    expect(issues[0].textContent).toContain("Available: region");
  });

  it("reports an invalid spec with its errors", async () => {
    await render(
      step({ result: sample({ dashboardValid: false, charts: [], errors: ["/charts: must be array"] }) }),
    );
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    await act(async () => chip.click());
    const band = q(container, '[data-testid="chat-dashboard-sample-invalid"]');
    expect(band?.textContent).toContain("not valid");
    expect(band?.textContent).toContain("/charts: must be array");
    expect(container.textContent).toContain("No charts were checked.");
  });

  it("degrades a legacy completion to the input pills", async () => {
    await render(step({ result: LEGACY }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    await act(async () => chip.click());
    expect(container.querySelectorAll('[data-testid="chat-dashboard-sample-chart"]').length).toBe(0);
    expect(q(container, '[data-testid="chat-dashboard-sample-card"]')?.textContent).toContain(
      "revenue.dashboard.json",
    );
  });
});
