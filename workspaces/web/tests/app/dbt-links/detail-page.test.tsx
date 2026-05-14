import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.resetModules();
  vi.unstubAllEnvs();
});

const mockLink = {
  schemaVersion: 1 as const,
  id: "aabbccdd-1234-4abc-8def-aabbccddeeff",
  name: "My dbt Project",
  kind: "native_upload" as const,
  createdAt: "2024-06-15T12:00:00.000Z",
  relativePath: "aabbccdd-1234-4abc-8def-aabbccddeeff",
};

describe("DbtLinkDetailPage", () => {
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
    const { default: Page } = await import("@/app/dbt-links/[id]/page");
    render(await Page({ params: Promise.resolve({ id: mockLink.id }) }));

    expect(screen.getByText("dbt project links are not available yet.")).toBeDefined();
  });

  it("calls notFound() when loadDbtLink returns null", async () => {
    vi.doMock("@/lib/env", () => ({
      getServerEnv: vi.fn(() => ({
        mode: "local",
        apiUrl: "http://localhost:3400",
        localApiKey: "test-key",
        localWorkspaceIds: [],
        localChartsDir: "/tmp/charts",
        localDbtLinksDir: "/tmp/dbt-links",
      })),
    }));

    vi.doMock("@/lib/dbt-links/load-links", () => ({
      loadDbtLink: vi.fn(async () => null),
    }));

    vi.doMock("next/navigation", () => ({
      notFound: () => {
        throw new Error("NEXT_NOT_FOUND");
      },
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/dbt-links/[id]/page");

    await expect(
      Page({ params: Promise.resolve({ id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("renders link name, kind label 'Native upload', and relativePath in a <code>", async () => {
    vi.doMock("@/lib/env", () => ({
      getServerEnv: vi.fn(() => ({
        mode: "local",
        apiUrl: "http://localhost:3400",
        localApiKey: "test-key",
        localWorkspaceIds: [],
        localChartsDir: "/tmp/charts",
        localDbtLinksDir: "/tmp/dbt-links",
      })),
    }));

    vi.doMock("@/lib/dbt-links/load-links", () => ({
      loadDbtLink: vi.fn(async () => mockLink),
    }));

    vi.doMock("next/navigation", () => ({
      notFound: () => {
        throw new Error("NEXT_NOT_FOUND");
      },
    }));

    vi.resetModules();
    const { default: Page } = await import("@/app/dbt-links/[id]/page");
    render(await Page({ params: Promise.resolve({ id: mockLink.id }) }));

    expect(screen.getByRole("heading", { level: 1, name: "My dbt Project" })).toBeDefined();
    // Kind label appears in the StatusPill
    expect(screen.getAllByText("Native upload").length).toBeGreaterThan(0);

    // relativePath rendered in <pre>
    const pathEl = screen.getByText(mockLink.relativePath);
    expect(pathEl.tagName.toLowerCase()).toBe("pre");
  });
});
