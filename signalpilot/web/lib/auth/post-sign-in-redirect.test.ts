import { describe, expect, it } from "vitest";
import { clerkFrontendApiOrigin, clerkTrustedOrigins, resolvePostSignInRedirect } from "./post-sign-in-redirect";

// "endless-fly-19.clerk.accounts.dev$" base64-encoded, the way Clerk builds publishable keys.
const PK = "pk_test_" + Buffer.from("endless-fly-19.clerk.accounts.dev$").toString("base64").replace(/=+$/, "");
const CLERK = "https://endless-fly-19.clerk.accounts.dev";

describe("clerkFrontendApiOrigin", () => {
  it("derives the frontend api origin from the publishable key", () => {
    expect(clerkFrontendApiOrigin(PK)).toBe(CLERK);
  });
  it("returns null for junk", () => {
    expect(clerkFrontendApiOrigin(undefined)).toBeNull();
    expect(clerkFrontendApiOrigin("sk_test_nope")).toBeNull();
    expect(clerkFrontendApiOrigin("pk_test_%%%")).toBeNull();
  });
});

describe("clerkTrustedOrigins", () => {
  it("includes the account portal for dev instances", () => {
    expect(clerkTrustedOrigins(PK)).toEqual([CLERK, "https://endless-fly-19.accounts.dev"]);
  });
  it("includes the account portal for production instances", () => {
    const prod = "pk_live_" + Buffer.from("clerk.signalpilot.ai$").toString("base64").replace(/=+$/, "");
    expect(clerkTrustedOrigins(prod)).toEqual(["https://clerk.signalpilot.ai", "https://accounts.signalpilot.ai"]);
  });
});

describe("resolvePostSignInRedirect", () => {
  it("allows the account portal consent page", () => {
    const target = "https://endless-fly-19.accounts.dev/oauth-consent?__clerk_db_jwt=dvb_x&scope=openid";
    expect(resolvePostSignInRedirect(`?redirect_url=${encodeURIComponent(target)}`, { publishableKey: PK })).toBe(target);
  });

  it("falls back to the dashboard without a redirect_url", () => {
    expect(resolvePostSignInRedirect("")).toBe("/dashboard");
    expect(resolvePostSignInRedirect("?foo=bar", { fallback: "/onboarding" })).toBe("/onboarding");
  });

  it("allows same-origin paths", () => {
    expect(resolvePostSignInRedirect("?redirect_url=%2Fprojects%2F1")).toBe("/projects/1");
  });

  it("rejects protocol-relative and foreign absolute urls", () => {
    expect(resolvePostSignInRedirect("?redirect_url=//evil.test/x", { publishableKey: PK })).toBe("/dashboard");
    expect(resolvePostSignInRedirect("?redirect_url=https://evil.test/x", { publishableKey: PK })).toBe("/dashboard");
    expect(resolvePostSignInRedirect("?redirect_url=javascript:alert(1)", { publishableKey: PK })).toBe("/dashboard");
  });

  it("allows the Clerk authorize continuation url so OAuth consent can finish", () => {
    const target = `${CLERK}/oauth/authorize-with-immediate-redirect?client_id=abc&state=1`;
    const search = `?redirect_url=${encodeURIComponent(target)}`;
    expect(resolvePostSignInRedirect(search, { publishableKey: PK })).toBe(target);
  });

  it("does not trust Clerk urls when the publishable key is unknown", () => {
    const target = `${CLERK}/oauth/authorize`;
    expect(resolvePostSignInRedirect(`?redirect_url=${encodeURIComponent(target)}`)).toBe("/dashboard");
  });
});
