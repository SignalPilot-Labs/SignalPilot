import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.resetModules();
  vi.unstubAllEnvs();
});

describe("DbtLinksPage", () => {
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
    const { default: Page } = await import("@/app/dbt-links/page");
    render(await Page());

    expect(screen.getByText("dbt project links are not available yet.")).toBeDefined();
  });

  it("renders empty-local body when local mode has no links", async () => {
    vi.doMock("@/lib/env", () => ({
      getServerEnv: vi.fn(() => ({
        mode: "local",
        apiUrl: "http://localhost:3400",
        localApiKey: "test-key",
        localWorkspaceIds: [],
        localChartsDir: "/tmp/test-charts",
        localDbtLinksDir: "/tmp/test-dbt-links",
      })),
    }));

    vi.doMock("@/lib/dbt-links/load-links", () => ({
      loadDbtLinks: vi.fn(async () => []),
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/dbt-links/page");
    render(await Page());

    expect(screen.getByText("No dbt project links yet. Upload one from New link.")).toBeDefined();
  });

  it("renders item names when local mode has links", async () => {
    const link1 = {
      schemaVersion: 1 as const,
      id: "11111111-1111-4111-8111-111111111111",
      name: "My dbt Project",
      kind: "native_upload" as const,
      createdAt: "2024-06-01T00:00:00.000Z",
      relativePath: "projects/my-dbt-project",
    };
    const link2 = {
      schemaVersion: 1 as const,
      id: "22222222-2222-4222-8222-222222222222",
      name: "Another Project",
      kind: "github" as const,
      createdAt: "2024-05-01T00:00:00.000Z",
      relativePath: "projects/another-project",
    };

    vi.doMock("@/lib/env", () => ({
      getServerEnv: vi.fn(() => ({
        mode: "local",
        apiUrl: "http://localhost:3400",
        localApiKey: "test-key",
        localWorkspaceIds: [],
        localChartsDir: "/tmp/test-charts",
        localDbtLinksDir: "/tmp/test-dbt-links",
      })),
    }));

    vi.doMock("@/lib/dbt-links/load-links", () => ({
      loadDbtLinks: vi.fn(async () => [link1, link2]),
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/dbt-links/page");
    render(await Page());

    expect(screen.getByText("My dbt Project")).toBeDefined();
    expect(screen.getByText("Another Project")).toBeDefined();
  });
});
