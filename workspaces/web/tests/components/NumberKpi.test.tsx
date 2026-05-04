import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { NumberKpi } from "@/components/charts/NumberKpi";
import type { ChartResponse, ChartRunResponse } from "@/lib/api/types";

afterEach(() => {
  cleanup();
});

function makeChart(overrides: Partial<ChartResponse> = {}): ChartResponse {
  return {
    id: "chart-1",
    workspace_id: "ws-1",
    title: "Revenue",
    chart_type: "number",
    echarts_option_json: {},
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    created_by: null,
    query: null,
    ...overrides,
  };
}

function makeRun(rows: unknown[][]): ChartRunResponse {
  return {
    chart_id: "chart-1",
    cache_key: "k",
    cached: false,
    computed_at: "2024-01-01T00:00:00Z",
    columns: [{ name: "value", type: "number" }],
    rows,
    truncated: false,
  };
}

describe("NumberKpi", () => {
  it("renders one <dl>, one <dd> and one <dt>", () => {
    const { container } = render(
      <NumberKpi chart={makeChart()} run={makeRun([[42]])} />
    );
    const dls = container.querySelectorAll("dl");
    const dds = container.querySelectorAll("dd");
    const dts = container.querySelectorAll("dt");
    expect(dls).toHaveLength(1);
    expect(dds).toHaveLength(1);
    expect(dts).toHaveLength(1);
  });

  it("displays the chart title in <dt>", () => {
    render(<NumberKpi chart={makeChart({ title: "Revenue" })} run={makeRun([[42]])} />);
    const dt = screen.getByText("Revenue", { selector: "dt" });
    expect(dt).toBeDefined();
  });

  it("displays the formatted value in <dd>", () => {
    const { container } = render(<NumberKpi chart={makeChart()} run={makeRun([[1000]])} />);
    const dd = container.querySelector("dd");
    expect(dd).not.toBeNull();
    expect(dd?.textContent).toContain("1");
  });

  it("<dd> precedes <dt> in source order", () => {
    const { container } = render(
      <NumberKpi chart={makeChart()} run={makeRun([[42]])} />
    );
    const dl = container.querySelector("dl");
    expect(dl).not.toBeNull();
    const children = Array.from(dl!.children);
    expect(children[0].tagName.toLowerCase()).toBe("dd");
    expect(children[1].tagName.toLowerCase()).toBe("dt");
  });

  it("renders — when value is null", () => {
    const { container } = render(<NumberKpi chart={makeChart()} run={makeRun([[null]])} />);
    const dd = container.querySelector("dd");
    expect(dd?.textContent).toBe("—");
  });
});
