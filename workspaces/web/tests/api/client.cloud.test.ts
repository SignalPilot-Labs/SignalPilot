import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

describe("apiFetch (cloud mode)", () => {
  beforeEach(() => {
    vi.stubEnv("WORKSPACES_MODE", "cloud");
    vi.stubEnv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "pk_test_xxx");
    vi.stubEnv("CLERK_SECRET_KEY", "sk_test_xxx");
    vi.stubEnv("WORKSPACES_API_URL", "http://api");
    // Do NOT stub SP_LOCAL_API_KEY — cloud mode must not read it
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("calls fetch with Authorization: Bearer <jwt> from Clerk in cloud mode", async () => {
    vi.doMock("@clerk/nextjs/server", () => ({
      auth: async () => ({
        getToken: async (_args: { template: string }) => "jwt-from-clerk",
      }),
    }));

    vi.resetModules();
    const { listCharts } = await import("@/lib/api/client");

    const mockResponse = {
      ok: true,
      json: async () => ({ items: [], next_cursor: null }),
    } as unknown as Response;

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(mockResponse);

    await listCharts("ws-1");

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [calledUrl, calledInit] = fetchSpy.mock.calls[0] as [string, RequestInit];

    expect(calledUrl).toBe("http://api/v1/charts?workspace=ws-1");

    const headers = calledInit.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer jwt-from-clerk");
  });

  it("rejects with AUTH_REQUIRED and does not call fetch when getToken returns null", async () => {
    vi.doMock("@clerk/nextjs/server", () => ({
      auth: async () => ({
        getToken: async (_args: { template: string }) => null,
      }),
    }));

    vi.resetModules();
    const { listCharts } = await import("@/lib/api/client");

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    await expect(listCharts("ws-1")).rejects.toThrow("AUTH_REQUIRED");

    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("throws from getServerEnv when CLERK_SECRET_KEY is missing", async () => {
    vi.doMock("@clerk/nextjs/server", () => ({
      auth: async () => ({
        getToken: async (_args: { template: string }) => "jwt-from-clerk",
      }),
    }));

    vi.unstubAllEnvs();
    vi.stubEnv("WORKSPACES_MODE", "cloud");
    vi.stubEnv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "pk_test_xxx");
    vi.stubEnv("WORKSPACES_API_URL", "http://api");
    // CLERK_SECRET_KEY intentionally not set

    vi.resetModules();
    const { listCharts } = await import("@/lib/api/client");

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    await expect(listCharts("ws-1")).rejects.toThrow("CLERK_SECRET_KEY");

    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
