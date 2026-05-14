import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.resetModules();
  vi.unstubAllEnvs();
});

// Mock next/navigation used by NewAgentRunForm
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

// Mock the server action imported by NewAgentRunForm
vi.mock("@/lib/agent-runs/save-run", () => ({
  saveAgentRun: vi.fn(),
}));

describe("AgentRunsNewPage", () => {
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
    const { default: Page } = await import("@/app/agent-runs/new/page");
    render(Page());

    expect(screen.getByText("Agent runs are not available yet in cloud mode.")).toBeDefined();
  });

  it("renders the prompt textarea in local mode", async () => {
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

    vi.resetModules();
    const { default: Page } = await import("@/app/agent-runs/new/page");
    render(Page());

    const textarea = screen.getByLabelText("Prompt");
    expect(textarea).toBeDefined();
    expect((textarea as HTMLTextAreaElement).tagName.toLowerCase()).toBe("textarea");
  });
});
