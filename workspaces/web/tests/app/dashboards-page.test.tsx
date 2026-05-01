import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.resetModules();
  vi.unstubAllEnvs();
});

describe("DashboardsPage", () => {
  it("renders WorkspaceList with ids when local mode has WORKSPACES_LOCAL_IDS", async () => {
    vi.doMock("@/lib/env", () => ({
      getServerEnv: vi.fn(() => ({
        mode: "local",
        apiUrl: "http://localhost:3400",
        localApiKey: "test-key",
        localWorkspaceIds: ["ws-1", "ws-2"],
      })),
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/dashboards/page");
    render(await Page());

    const links = screen.getAllByRole("link");
    const hrefs = links.map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/dashboards/ws-1");
    expect(hrefs).toContain("/dashboards/ws-2");
  });

  it("renders empty-state copy when local mode has no ids", async () => {
    vi.doMock("@/lib/env", () => ({
      getServerEnv: vi.fn(() => ({
        mode: "local",
        apiUrl: "http://localhost:3400",
        localApiKey: "test-key",
        localWorkspaceIds: [],
      })),
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/dashboards/page");
    render(await Page());

    expect(screen.getByText(/Set WORKSPACES_LOCAL_IDS/)).toBeDefined();
  });

  it("renders cloud-deferred empty state in cloud mode", async () => {
    vi.doMock("@/lib/env", () => ({
      getServerEnv: vi.fn(() => ({
        mode: "cloud",
        apiUrl: "http://api",
        clerkPublishableKey: "pk_test_xxx",
        clerkSecretKey: "sk_test_xxx",
      })),
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/dashboards/page");
    render(await Page());

    expect(screen.getByText("Workspace listing is not available yet.")).toBeDefined();
  });
});
