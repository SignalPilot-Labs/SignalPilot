import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { DashboardScreenshotResult, RunStep } from "~/lib/chat-run-steps";
import { ToolCard } from "../tool-card";
import { summarizeDashboardScreenshot } from "./dashboard-screenshot-card";

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

const shot = (
  overrides: Partial<DashboardScreenshotResult> = {},
): DashboardScreenshotResult => ({
  kind: "dashboard_screenshot",
  summary: "Rendered 3 charts",
  resultText: "{}",
  resultChars: 2,
  truncated: false,
  errorMessage: null,
  dashboardValid: true,
  errors: [],
  rendered: ["kpi_revenue", "revenue_trend", "region_share"],
  failed: [],
  width: 1280,
  height: 720,
  previewPath: ".dashboard-previews/revenue-1725800000.png",
  error: null,
  ...overrides,
});

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "s1",
    sequence: 41,
    category: "artifact",
    status: "succeeded",
    title: "Rendering dashboard",
    tool: "dashboard_screenshot",
    toolOrigin: "chat",
    input: { path: "artifacts/revenue.dashboard.json", width: 1280, theme: "light" },
    sql: null,
    code: null,
    file: null,
    sources: [],
    detail: null,
    result: null,
    startedAt: "2026-09-01T12:00:00.000Z",
    endedAt: "2026-09-01T12:00:01.200Z",
    durationMs: 1200,
    children: [],
    subagentType: null,
    report: null,
    liveText: "",
    ...overrides,
  };
}

const q = (root: ParentNode, selector: string) => root.querySelector(selector);

describe("summarizeDashboardScreenshot", () => {
  it("counts rendered and failed charts", () => {
    expect(summarizeDashboardScreenshot(step({ result: shot() }))).toEqual({
      title: "Dashboard render",
      stat: "Rendered 3 charts",
      ok: true,
    });
    expect(
      summarizeDashboardScreenshot(
        step({
          result: shot({
            rendered: ["kpi_revenue"],
            failed: [{ id: "region_share", code: "missing_column", message: "revenue is missing" }],
          }),
        }),
      ).stat,
    ).toBe("Rendered 1 chart, 1 failed");
  });
  it("is not ok when the renderer was unavailable or the step failed", () => {
    expect(summarizeDashboardScreenshot(step())).toEqual({
      title: "Dashboard render",
      stat: null,
      ok: true,
    });
    expect(summarizeDashboardScreenshot(step({ status: "failed" })).ok).toBe(false);
    expect(
      summarizeDashboardScreenshot(
        step({ result: shot({ rendered: [], error: "renderer_unavailable" }) }),
      ),
    ).toEqual({ title: "Dashboard render", stat: "renderer_unavailable", ok: false });
  });
});

describe("dashboard screenshot card", () => {
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
    const body = q(container, '[data-testid="chat-dashboard-screenshot-card"]');
    expect(body?.textContent).toContain("revenue.dashboard.json");
    expect(body?.textContent).toContain("Rendering dashboard…");
  });

  it("expands to rendered chips, the failed list and the canvas size", async () => {
    await render(
      step({
        result: shot({
          rendered: ["kpi_revenue", "revenue_trend"],
          failed: [{ id: "region_share", code: "missing_column", message: "revenue is missing" }],
        }),
      }),
    );
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("Rendered 2 charts, 1 failed");
    await act(async () => chip.click());
    const rendered = container.querySelectorAll('[data-testid="chat-dashboard-screenshot-rendered"]');
    expect([...rendered].map((node) => node.textContent)).toEqual(["kpi_revenue", "revenue_trend"]);
    const failed = container.querySelectorAll('[data-testid="chat-dashboard-screenshot-failed"]');
    expect(failed.length).toBe(1);
    expect(failed[0].textContent).toContain("region_share");
    expect(failed[0].textContent).toContain("missing_column");
    expect(failed[0].textContent).toContain("revenue is missing");
    expect(container.textContent).toContain("1280 × 720");
    expect(container.textContent).toContain(".dashboard-previews/revenue-1725800000.png");
    // No image: the PNG is not carried on the event.
    expect(container.querySelector("img")).toBeNull();
  });

  it("explains a missing renderer", async () => {
    await render(step({ result: shot({ rendered: [], error: "renderer_unavailable", width: null, height: null, previewPath: null }) }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-dashboard-screenshot-error"]')?.textContent).toContain(
      "renderer is not available",
    );
  });

  it("degrades a legacy completion to the input pills", async () => {
    await render(step({ result: LEGACY }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    await act(async () => chip.click());
    expect(container.querySelectorAll('[data-testid="chat-dashboard-screenshot-rendered"]').length).toBe(0);
    expect(q(container, '[data-testid="chat-dashboard-screenshot-card"]')?.textContent).toContain(
      "revenue.dashboard.json",
    );
  });
});
