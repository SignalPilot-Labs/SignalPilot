import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.resetModules();
  vi.unstubAllEnvs();
});

function stubLocalEnv() {
  vi.doMock("@/lib/env", () => ({
    getServerEnv: vi.fn(() => ({
      mode: "local",
      apiUrl: "http://localhost:3400",
      localApiKey: "test-key",
      localWorkspaceIds: [],
      localChartsDir: "/tmp/charts",
      localDbtLinksDir: "/tmp/dbt-links",
      localAgentRunsDir: "/tmp/agent-runs",
    })),
  }));
}

describe("AgentRunsPage", () => {
  it("renders CLOUD_DEFERRED_BODY in cloud mode", async () => {
    vi.doMock("@/lib/env", () => ({
      getServerEnv: vi.fn(() => ({
        mode: "cloud",
        apiUrl: "http://api",
        clerkPublishableKey: "pk_test_xxx",
        clerkSecretKey: "sk_test_xxx",
      })),
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/agent-runs/page");
    render(await Page());

    expect(screen.getByText("Agent runs are not available yet in cloud mode.")).toBeDefined();
  });

  it("renders EMPTY_LOCAL_BODY when local mode has no runs", async () => {
    stubLocalEnv();

    vi.doMock("@/lib/agent-runs/load-runs", () => ({
      loadAgentRuns: vi.fn(async () => []),
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/agent-runs/page");
    render(await Page());

    expect(screen.getByText("No agent runs yet. Start one from New agent run.")).toBeDefined();
  });

  it("renders AgentRunList when local mode has runs", async () => {
    stubLocalEnv();

    const run1 = {
      schemaVersion: 1 as const,
      id: "11111111-1111-4111-8111-111111111111",
      prompt: "Analyze the sales data",
      status: "pending" as const,
      createdAt: "2024-06-01T00:00:00.000Z",
    };
    const run2 = {
      schemaVersion: 1 as const,
      id: "22222222-2222-4222-8222-222222222222",
      prompt: "Generate monthly report",
      status: "succeeded" as const,
      createdAt: "2024-05-01T00:00:00.000Z",
    };

    vi.doMock("@/lib/agent-runs/load-runs", () => ({
      loadAgentRuns: vi.fn(async () => [run1, run2]),
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/agent-runs/page");
    render(await Page());

    expect(screen.getByText("Analyze the sales data")).toBeDefined();
    expect(screen.getByText("Generate monthly report")).toBeDefined();
  });
});
