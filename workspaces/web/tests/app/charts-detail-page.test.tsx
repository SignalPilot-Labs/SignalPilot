import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.resetModules();
  vi.unstubAllEnvs();
});

vi.mock("@/components/charts/EChart", () => ({
  EChart: ({ option, ariaLabel }: { option: unknown; ariaLabel: string }) => (
    <div data-testid="echart-stub" data-option={JSON.stringify(option)} aria-label={ariaLabel} />
  ),
}));

const mockDefinition = {
  schemaVersion: 1 as const,
  id: "aabbccdd-1234-4abc-8def-aabbccddeeff",
  name: "My Test Chart",
  type: "bar" as const,
  sql: "SELECT 1 FROM dual",
  createdAt: "2024-06-15T12:00:00.000Z",
};

describe("ChartDetailPage", () => {
  it("renders chart name, type, and SQL inside a <pre> for a valid definition", async () => {
    vi.doMock("@/lib/env", () => ({
      getServerEnv: vi.fn(() => ({
        mode: "local",
        apiUrl: "http://localhost:3400",
        localApiKey: "test-key",
        localWorkspaceIds: [],
        localChartsDir: "/tmp/test-charts",
      })),
    }));

    vi.doMock("@/lib/charts/load-charts", () => ({
      loadChartDefinition: vi.fn(async () => mockDefinition),
    }));

    vi.doMock("next/navigation", () => ({
      notFound: () => {
        throw new Error("NEXT_NOT_FOUND");
      },
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/charts/[id]/page");
    render(await Page({ params: Promise.resolve({ id: mockDefinition.id }) }));

    expect(screen.getByRole("heading", { level: 1, name: "My Test Chart" })).toBeDefined();
    expect(screen.getByText("bar")).toBeDefined();

    const sqlNode = screen.getByText("SELECT 1 FROM dual");
    const preEl = sqlNode.closest("pre");
    expect(preEl).not.toBeNull();
  });

  it("renders Preview heading and sample data disclaimer", async () => {
    vi.doMock("@/lib/env", () => ({
      getServerEnv: vi.fn(() => ({
        mode: "local",
        apiUrl: "http://localhost:3400",
        localApiKey: "test-key",
        localWorkspaceIds: [],
        localChartsDir: "/tmp/test-charts",
      })),
    }));

    vi.doMock("@/lib/charts/load-charts", () => ({
      loadChartDefinition: vi.fn(async () => mockDefinition),
    }));

    vi.doMock("next/navigation", () => ({
      notFound: () => {
        throw new Error("NEXT_NOT_FOUND");
      },
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/charts/[id]/page");
    render(await Page({ params: Promise.resolve({ id: mockDefinition.id }) }));

    expect(screen.getByRole("heading", { name: "Preview" })).toBeDefined();
    expect(screen.getByText("Sample data — query execution not yet wired")).toBeDefined();
  });

  it("calls notFound() when loadChartDefinition returns null", async () => {
    vi.doMock("@/lib/env", () => ({
      getServerEnv: vi.fn(() => ({
        mode: "local",
        apiUrl: "http://localhost:3400",
        localApiKey: "test-key",
        localWorkspaceIds: [],
        localChartsDir: "/tmp/test-charts",
      })),
    }));

    vi.doMock("@/lib/charts/load-charts", () => ({
      loadChartDefinition: vi.fn(async () => null),
    }));

    vi.doMock("next/navigation", () => ({
      notFound: () => {
        throw new Error("NEXT_NOT_FOUND");
      },
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/charts/[id]/page");

    await expect(
      Page({ params: Promise.resolve({ id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });
});
