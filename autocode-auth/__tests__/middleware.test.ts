import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextResponse } from "next/server";

// Mock auth to be a passthrough — it receives the callback and returns it as-is
vi.mock("@/lib/auth", () => ({
  auth: (callback: Function) => callback,
}));

import middleware, { config } from "@/middleware";

function makeRequest(pathname: string, isAuthenticated: boolean) {
  const url = new URL(pathname, "http://localhost:3000");
  return {
    auth: isAuthenticated ? { user: { id: "user-1" } } : null,
    nextUrl: url,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("middleware", () => {
  // 1. Unauthenticated user hitting /setup → redirected to /signup
  it("redirects unauthenticated user on /setup to /signup", () => {
    const response = middleware(makeRequest("/setup", false));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/signup");
  });

  // 2. Unauthenticated user hitting /setup/something → redirected to /signup
  it("redirects unauthenticated user on /setup/something to /signup", () => {
    const response = middleware(makeRequest("/setup/something", false));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/signup");
  });

  // 3. Authenticated user hitting /setup → passes through (NextResponse.next())
  it("allows authenticated user on /setup to pass through", () => {
    const response = middleware(makeRequest("/setup", true));
    expect(response.headers.get("location")).toBeNull();
  });

  // 4. Unauthenticated user hitting /dashboard → redirected to /signup (auth guard fires first)
  it("redirects unauthenticated user on /dashboard to /signup", () => {
    const response = middleware(makeRequest("/dashboard", false));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/signup");
  });

  // 5. Authenticated user hitting /dashboard → redirected to /setup
  it("redirects authenticated user on /dashboard to /setup", () => {
    const response = middleware(makeRequest("/dashboard", true));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/setup");
  });

  // 6. Authenticated user hitting /dashboard/settings → redirected to /setup
  it("redirects authenticated user on /dashboard/settings to /setup", () => {
    const response = middleware(makeRequest("/dashboard/settings", true));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/setup");
  });

  // 7. config.matcher includes the correct patterns
  it("config.matcher includes /setup and /dashboard path patterns", () => {
    expect(config.matcher).toContain("/setup/:path*");
    expect(config.matcher).toContain("/dashboard/:path*");
  });
});
