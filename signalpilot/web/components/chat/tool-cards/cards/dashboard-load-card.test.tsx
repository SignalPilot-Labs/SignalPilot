import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { DashboardLoadResult, RunStep } from "~/lib/chat-run-steps";
import { ToolCard } from "../tool-card";
import { summarizeDashboardLoad } from "./dashboard-load-card";

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

const loaded = (overrides: Partial<DashboardLoadResult> = {}): DashboardLoadResult => ({
  kind: "dashboard_load",
  summary: "Loaded Revenue overview v3",
  resultText: "{}",
  resultChars: 2,
  truncated: false,
  errorMessage: null,
  path: "artifacts/revenue.dashboard.json",
  dashboard: { id: "dash_1", slug: "revenue", name: "Revenue overview", versionNo: 3, chartCount: 9 },
  datasets: [
    { name: "summary", rows: 1, snapshot: "artifacts/datasets/summary.csv" },
    { name: "revenue_monthly", rows: 48, snapshot: "artifacts/datasets/revenue_monthly.csv" },
  ],
  datasetsTruncated: false,
  next: "Edit the spec, then ask the user to publish it as a new version.",
  error: null,
  message: null,
  ...overrides,
});

const refused = (): DashboardLoadResult =>
  loaded({
    path: null,
    dashboard: null,
    datasets: [],
    next: null,
    error: "not_found",
    message: 'No published dashboard has the slug "revenue".',
  });

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "d0",
    sequence: 39,
    category: "notebook",
    status: "succeeded",
    title: "Loading dashboard",
    tool: "dashboard_load_published",
    toolOrigin: "chat",
    input: { slug: "revenue" },
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

describe("summarizeDashboardLoad", () => {
  it("names the loaded version", () => {
    expect(summarizeDashboardLoad(step({ result: loaded() }))).toEqual({
      title: "Dashboard load",
      stat: "Loaded Revenue overview v3",
      ok: true,
    });
    const unversioned = loaded({ dashboard: { ...loaded().dashboard!, versionNo: null } });
    expect(summarizeDashboardLoad(step({ result: unversioned })).stat).toBe("Loaded Revenue overview");
  });
  it("surfaces the refusal message and is not ok", () => {
    expect(summarizeDashboardLoad(step({ result: refused() }))).toEqual({
      title: "Dashboard load",
      stat: 'No published dashboard has the slug "revenue".',
      ok: false,
    });
    expect(summarizeDashboardLoad(step())).toEqual({ title: "Dashboard load", stat: null, ok: true });
    expect(summarizeDashboardLoad(step({ status: "failed" })).ok).toBe(false);
  });
});

describe("dashboard load card", () => {
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
  const open = async () => {
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    await act(async () => chip.click());
    return chip;
  };

  it("shows the input pills and a progress rail while running", async () => {
    await render(step({ status: "running", endedAt: null, durationMs: null }));
    const body = q(container, '[data-testid="chat-dashboard-load-card"]');
    expect(body?.textContent).toContain("revenue");
    expect(body?.textContent).toContain("Loading dashboard…");
  });

  it("expands to the path and the dataset rows", async () => {
    await render(step({ result: loaded() }));
    const chip = await open();
    expect(chip.textContent).toContain("Loaded Revenue overview v3");
    expect(q(container, '[data-testid="chat-dashboard-load-name"]')?.textContent).toBe(
      "Revenue overview v3",
    );
    expect(q(container, '[data-testid="chat-dashboard-load-path"]')?.textContent).toBe(
      "artifacts/revenue.dashboard.json",
    );
    expect(container.textContent).toContain("9 charts");
    const rows = container.querySelectorAll('[data-testid="chat-dashboard-load-dataset"]');
    expect(rows.length).toBe(2);
    expect(rows[1].getAttribute("data-dataset")).toBe("revenue_monthly");
    expect(rows[1].textContent).toContain("48");
    expect(rows[1].textContent).toContain("artifacts/datasets/revenue_monthly.csv");
    expect(container.textContent).toContain("publish it as a new version");
    expect(q(container, '[data-testid="chat-dashboard-load-error"]')).toBeNull();
  });

  it("shows the refusal message in the error state", async () => {
    await render(step({ result: refused() }));
    await open();
    const error = q(container, '[data-testid="chat-dashboard-load-error"]');
    expect(error?.textContent).toContain('No published dashboard has the slug "revenue".');
    expect(error?.textContent).toContain("not_found");
    expect(container.querySelectorAll('[data-testid="chat-dashboard-load-dataset"]').length).toBe(0);
  });

  it("degrades a legacy completion to the input pills", async () => {
    await render(step({ result: LEGACY }));
    await open();
    expect(q(container, '[data-testid="chat-dashboard-load-path"]')).toBeNull();
    expect(q(container, '[data-testid="chat-dashboard-load-card"]')?.textContent).toContain("revenue");
  });
});
