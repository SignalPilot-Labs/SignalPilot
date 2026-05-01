import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { DataTable } from "@/components/charts/DataTable";
import type { ChartRunResponse } from "@/lib/api/types";

afterEach(() => {
  cleanup();
});

function makeRun(overrides: Partial<ChartRunResponse> = {}): ChartRunResponse {
  return {
    chart_id: "chart-1",
    cache_key: "k",
    cached: false,
    computed_at: "2024-01-01T00:00:00Z",
    columns: [{ name: "col1", type: "string" }, { name: "col2", type: "number" }],
    rows: [["foo", 1], ["bar", 2]],
    truncated: false,
    ...overrides,
  };
}

describe("DataTable", () => {
  it("renders <caption> with sr-only class containing the caption string", () => {
    render(<DataTable run={makeRun()} caption="Sales Summary" />);
    const caption = screen.getByText("Sales Summary", { selector: "caption" });
    expect(caption).toBeDefined();
    expect(caption.className).toContain("sr-only");
  });

  it("outer wrapper uses new dark border token", () => {
    const { container } = render(<DataTable run={makeRun()} caption="Test" />);
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.className).toContain("border-[var(--color-border)]");
  });

  it("table rows have table-row-hover class", () => {
    const { container } = render(<DataTable run={makeRun()} caption="Test" />);
    const rows = container.querySelectorAll("tbody tr");
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect((row as HTMLElement).className).toContain("table-row-hover");
    }
  });

  it("renders all data rows", () => {
    const { getAllByText } = render(<DataTable run={makeRun()} caption="Test" />);
    expect(getAllByText("foo").length).toBeGreaterThan(0);
    expect(getAllByText("bar").length).toBeGreaterThan(0);
  });
});
