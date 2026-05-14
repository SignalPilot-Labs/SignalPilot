import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.resetModules();
  vi.unstubAllEnvs();
});

// Mock next/navigation (used internally by some components)
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

// Mock the server action — not called in render, but imported by NewDbtLinkForm
vi.mock("@/lib/dbt-links/save-link", () => ({
  saveDbtLinkNativeUpload: vi.fn(),
}));

describe("DbtLinksNewPage", () => {
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
    const { default: Page } = await import("@/app/dbt-links/new/page");
    render(Page());

    expect(screen.getByText("dbt project links are not available yet.")).toBeDefined();
  });

  it("renders <form> with name input and file input in local mode", async () => {
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

    vi.resetModules();
    const { default: Page } = await import("@/app/dbt-links/new/page");
    render(Page());

    expect(screen.getByLabelText("Name")).toBeDefined();
    // File input for .tar.gz upload
    const fileInput = screen.getByLabelText(/dbt project archive/i);
    expect(fileInput).toBeDefined();
    expect((fileInput as HTMLInputElement).type).toBe("file");
  });
});
