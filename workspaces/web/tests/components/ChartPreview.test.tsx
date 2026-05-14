import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import type { ChartDefinitionV1 } from "@/lib/charts/types";

afterEach(() => {
  cleanup();
});

vi.mock("@/components/charts/EChart", () => ({
  EChart: ({ option, ariaLabel }: { option: unknown; ariaLabel: string }) => (
    <div data-testid="echart-stub" data-option={JSON.stringify(option)} aria-label={ariaLabel} />
  ),
}));

function makeDef(overrides: Partial<ChartDefinitionV1> = {}): ChartDefinitionV1 {
  return {
    schemaVersion: 1,
    id: "bbbbbbbb-0000-4000-8000-bbbbbbbbbbbb",
    name: "Preview Test Chart",
    type: "bar",
    sql: "SELECT 1",
    createdAt: "2024-03-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("ChartPreview", () => {
  it("bar def renders echart-stub with xAxis and series in data-option", async () => {
    const { ChartPreview } = await import("@/components/charts/preview/ChartPreview");
    const def = makeDef({ type: "bar" });
    render(<ChartPreview definition={def} />);

    const stub = screen.getByTestId("echart-stub");
    expect(stub).toBeDefined();

    const raw = stub.getAttribute("data-option");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string) as Record<string, unknown>;
    expect(parsed).toHaveProperty("xAxis");
    expect(parsed).toHaveProperty("series");
  });

  it("line def renders echart-stub with xAxis and series in data-option", async () => {
    const { ChartPreview } = await import("@/components/charts/preview/ChartPreview");
    const def = makeDef({ type: "line" });
    render(<ChartPreview definition={def} />);

    const stub = screen.getByTestId("echart-stub");
    expect(stub).toBeDefined();

    const raw = stub.getAttribute("data-option");
    const parsed = JSON.parse(raw as string) as Record<string, unknown>;
    expect(parsed).toHaveProperty("xAxis");
    expect(parsed).toHaveProperty("series");
  });

  it("table def renders a <table> element", async () => {
    const { ChartPreview } = await import("@/components/charts/preview/ChartPreview");
    const def = makeDef({ type: "table" });
    render(<ChartPreview definition={def} />);

    expect(screen.getByRole("table")).toBeDefined();
  });

  it("kpi def renders the numeric value", async () => {
    const { ChartPreview } = await import("@/components/charts/preview/ChartPreview");
    const def = makeDef({ type: "kpi" });
    render(<ChartPreview definition={def} />);

    // The kpi value is a number; find any numeric text in the rendered output
    const allText = document.body.textContent ?? "";
    expect(allText).toMatch(/\d/);
  });

  it("renders the sample data disclaimer in all cases (bar)", async () => {
    const { ChartPreview } = await import("@/components/charts/preview/ChartPreview");
    render(<ChartPreview definition={makeDef({ type: "bar" })} />);
    expect(screen.getByText("Sample data — query execution not yet wired")).toBeDefined();
  });

  it("renders the sample data disclaimer in all cases (table)", async () => {
    const { ChartPreview } = await import("@/components/charts/preview/ChartPreview");
    render(<ChartPreview definition={makeDef({ type: "table" })} />);
    expect(screen.getByText("Sample data — query execution not yet wired")).toBeDefined();
  });

  it("renders the sample data disclaimer in all cases (kpi)", async () => {
    const { ChartPreview } = await import("@/components/charts/preview/ChartPreview");
    render(<ChartPreview definition={makeDef({ type: "kpi" })} />);
    expect(screen.getByText("Sample data — query execution not yet wired")).toBeDefined();
  });

  it("renders a Preview heading", async () => {
    const { ChartPreview } = await import("@/components/charts/preview/ChartPreview");
    render(<ChartPreview definition={makeDef()} />);
    expect(screen.getByRole("heading", { name: "Preview" })).toBeDefined();
  });
});
