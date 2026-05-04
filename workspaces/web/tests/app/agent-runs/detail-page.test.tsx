import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.resetModules();
  vi.unstubAllEnvs();
});

const mockRun = {
  schemaVersion: 1 as const,
  id: "aabbccdd-1234-4abc-8def-aabbccddeeff",
  prompt: "Analyze the sales data and produce a summary report",
  status: "pending" as const,
  createdAt: "2024-06-15T12:00:00.000Z",
};

describe("AgentRunDetailPage", () => {
  it("renders CLOUD_DEFERRED_BODY in cloud mode", async () => {
    vi.doMock("@/lib/env", () => ({
      getServerEnv: vi.fn(() => ({
        mode: "cloud",
        apiUrl: "http://api",
        clerkPublishableKey: "pk_test_xxx",
        clerkSecretKey: "sk_test_xxx",
      })),
    }));

    vi.doMock("next/navigation", () => ({
      notFound: () => {
        throw new Error("NEXT_NOT_FOUND");
      },
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/agent-runs/[id]/page");
    render(await Page({ params: Promise.resolve({ id: mockRun.id }) }));

    expect(screen.getByText("Agent runs are not available yet in cloud mode.")).toBeDefined();
  });

  it("calls notFound() sentinel when loadAgentRun returns null", async () => {
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

    vi.doMock("@/lib/agent-runs/load-runs", () => ({
      loadAgentRun: vi.fn(async () => null),
    }));

    vi.doMock("next/navigation", () => ({
      notFound: () => {
        throw new Error("NEXT_NOT_FOUND");
      },
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/agent-runs/[id]/page");

    await expect(
      Page({ params: Promise.resolve({ id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("renders run detail for local happy path", async () => {
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

    vi.doMock("@/lib/agent-runs/load-runs", () => ({
      loadAgentRun: vi.fn(async () => mockRun),
    }));

    vi.doMock("next/navigation", () => ({
      notFound: () => {
        throw new Error("NEXT_NOT_FOUND");
      },
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/agent-runs/[id]/page");
    render(await Page({ params: Promise.resolve({ id: mockRun.id }) }));

    // Heading is first line of prompt sliced to 80 chars
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Analyze the sales data and produce a summary report",
      }),
    ).toBeDefined();
    expect(screen.getByText("Pending")).toBeDefined();
  });
});
