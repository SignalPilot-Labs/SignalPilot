import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextResponse } from "next/server";

// Mock auth to be a passthrough — it receives the callback and returns it as-is
vi.mock("@/lib/auth", () => ({
  auth: (callback: Function) => callback,
}));

import proxy, { config } from "@/middleware";

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
    const response = proxy(makeRequest("/setup", false));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/signup");
  });

  // 2. Unauthenticated user hitting /setup/something → redirected to /signup
  it("redirects unauthenticated user on /setup/something to /signup", () => {
    const response = proxy(makeRequest("/setup/something", false));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/signup");
  });

  // 3. Authenticated user hitting /setup → passes through (NextResponse.next())
  it("allows authenticated user on /setup to pass through", () => {
    const response = proxy(makeRequest("/setup", true));
    expect(response.headers.get("location")).toBeNull();
  });

  // 4. Unprotected paths pass through for unauthenticated users
  it("passes through unauthenticated user on unprotected path", () => {
    const response = proxy(makeRequest("/signin", false));
    expect(response.headers.get("location")).toBeNull();
  });

  // 5. config.matcher includes the correct patterns
  it("config.matcher includes /setup path pattern", () => {
    expect(config.matcher).toContain("/setup/:path*");
  });
});
