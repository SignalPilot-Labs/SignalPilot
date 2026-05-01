import { describe, it, expect, vi, afterEach } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("listCharts", () => {
  it("sends Authorization header and correct URL when both env vars are set", async () => {
    vi.stubEnv("WORKSPACES_API_URL", "http://api.test");
    vi.stubEnv("SP_LOCAL_API_KEY", "secret-key-123");

    const mockResponse = {
      ok: true,
      json: async () => ({ items: [], next_cursor: null }),
    } as unknown as Response;

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(mockResponse);

    // Dynamic import after env stubs so getServerEnv() reads the stubbed values
    const { listCharts } = await import("@/lib/api/client");
    await listCharts("ws-1");

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [calledUrl, calledInit] = fetchSpy.mock.calls[0] as [string, RequestInit];

    expect(calledUrl).toContain("/v1/charts");
    expect(calledUrl).toContain("workspace=ws-1");

    const headers = calledInit.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer secret-key-123");
  });

  it("throws and does not call fetch when SP_LOCAL_API_KEY is missing", async () => {
    vi.stubEnv("WORKSPACES_API_URL", "http://api.test");
    vi.stubEnv("SP_LOCAL_API_KEY", "");

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // Re-import to pick up the new env state
    vi.resetModules();
    const { listCharts } = await import("@/lib/api/client");

    await expect(listCharts("ws-1")).rejects.toThrow("SP_LOCAL_API_KEY");

    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
