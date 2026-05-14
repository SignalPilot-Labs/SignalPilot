import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.resetModules();
  vi.unstubAllEnvs();
});

describe("ChartsPage", () => {
  it("renders both chart names as links to /charts/<id> in local mode with items", async () => {
    const chart1 = {
      schemaVersion: 1 as const,
      id: "11111111-1111-4111-8111-111111111111",
      name: "Revenue Chart",
      type: "bar" as const,
      sql: "SELECT revenue FROM sales",
      createdAt: "2024-06-01T00:00:00.000Z",
    };
    const chart2 = {
      schemaVersion: 1 as const,
      id: "22222222-2222-4222-8222-222222222222",
      name: "User Count",
      type: "kpi" as const,
      sql: "SELECT count(*) FROM users",
      createdAt: "2024-05-01T00:00:00.000Z",
    };

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
      loadChartDefinitions: vi.fn(async () => [chart1, chart2]),
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/charts/page");
    render(await Page());

    const links = screen.getAllByRole("link");
    const hrefs = links.map((l) => l.getAttribute("href"));
    expect(hrefs).toContain(`/charts/${chart1.id}`);
    expect(hrefs).toContain(`/charts/${chart2.id}`);
    expect(screen.getByText("Revenue Chart")).toBeDefined();
    expect(screen.getByText("User Count")).toBeDefined();
  });

  it("renders empty-local body when local mode has no saved charts", async () => {
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
      loadChartDefinitions: vi.fn(async () => []),
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/charts/page");
    render(await Page());

    expect(screen.getByText("No charts saved yet. Create one from New chart.")).toBeDefined();
  });

  it("renders cloud-deferred copy in cloud mode", async () => {
    vi.doMock("@/lib/env", () => ({
      getServerEnv: vi.fn(() => ({
        mode: "cloud",
        apiUrl: "http://api",
        clerkPublishableKey: "pk_test_xxx",
        clerkSecretKey: "sk_test_xxx",
      })),
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/charts/page");
    render(await Page());

    expect(screen.getByText("Chart builder coming soon.")).toBeDefined();
  });
});
