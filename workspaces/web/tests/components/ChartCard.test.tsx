import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import type { ChartResponse, ChartRunResponse } from "@/lib/api/types";

afterEach(() => {
  cleanup();
});

vi.mock("@/components/charts/EChart", () => ({
  EChart: ({ ariaLabel }: { ariaLabel: string; option: Record<string, unknown>; height?: number }) => (
    <div data-testid="echart-stub" aria-label={ariaLabel} />
  ),
}));

vi.mock("@/lib/echarts/map-option", () => ({
  mapToEChartsOption: () => ({}),
}));

// Import after mocks are set up
const { ChartCard } = await import("@/components/charts/ChartCard");

function makeChart(overrides: Partial<ChartResponse> = {}): ChartResponse {
  return {
    id: "chart-1",
    workspace_id: "ws-1",
    title: "Test Chart",
    chart_type: "line",
    echarts_option_json: {},
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    created_by: null,
    query: null,
    ...overrides,
  };
}

function makeRun(overrides: Partial<ChartRunResponse> = {}): ChartRunResponse {
  return {
    chart_id: "chart-1",
    cache_key: "k",
    cached: false,
    computed_at: "2024-01-01T00:00:00Z",
    columns: [{ name: "x", type: "string" }, { name: "y", type: "number" }],
    rows: [["a", 1]],
    truncated: false,
    ...overrides,
  };
}

describe("ChartCard", () => {
  it("renders <h2> with text-base font-semibold for chart_type line", () => {
    const chart = makeChart({ chart_type: "line" });
    render(<ChartCard chart={chart} runResult={makeRun()} />);
    const heading = screen.getByRole("heading", { level: 2 });
    expect(heading).toBeDefined();
    expect(heading.className).toContain("text-base");
    expect(heading.className).toContain("font-semibold");
  });

  it("suppresses <h2> for chart_type number", () => {
    const chart = makeChart({ chart_type: "number" });
    const run = makeRun({ columns: [{ name: "val", type: "number" }], rows: [[42]] });
    render(<ChartCard chart={chart} runResult={run} />);
    const heading = screen.queryByRole("heading", { level: 2 });
    expect(heading).toBeNull();
  });

  it("passes chart.title to EChart stub as aria-label", () => {
    const chart = makeChart({ chart_type: "line", title: "My Line Chart" });
    render(<ChartCard chart={chart} runResult={makeRun()} />);
    const stub = screen.getByTestId("echart-stub");
    expect(stub.getAttribute("aria-label")).toBe("My Line Chart");
  });

  it("renders <table> with <caption> containing chart.title for chart_type table", () => {
    const chart = makeChart({ chart_type: "table", title: "Sales Data" });
    render(<ChartCard chart={chart} runResult={makeRun()} />);
    const caption = screen.getByText("Sales Data", { selector: "caption" });
    expect(caption).toBeDefined();
    expect(caption.className).toContain("sr-only");
  });
});
