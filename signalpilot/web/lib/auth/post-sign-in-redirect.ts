/**
 * Where to send a user after they sign in.
 *
 * Clerk redirects OAuth authorization requests from signed-out users to our
 * sign-in page with `?redirect_url=<Clerk authorize URL>`. Once the session
 * exists we must send the browser back there so the OAuth consent flow (MCP
 * clients signing in with SignalPilot) can finish. Only two destinations are
 * honoured, everything else falls back, so this can never be an open redirect:
 *
 * - a same-origin path (`/projects/123`)
 * - an absolute URL on a Clerk-hosted origin derived from the publishable key:
 *   the Frontend API (`https://clerk.example.com`, `https://x.clerk.accounts.dev`)
 *   or the Account Portal that serves the OAuth consent screen
 *   (`https://accounts.example.com`, `https://x.accounts.dev`)
 */

export const DEFAULT_POST_SIGN_IN_PATH = "/dashboard";

export function clerkFrontendApiOrigin(publishableKey: string | undefined): string | null {
  if (!publishableKey) return null;
  const match = /^pk_(?:test|live)_(.+)$/.exec(publishableKey.trim());
  if (!match) return null;
  try {
    const decoded = atob(match[1].padEnd(match[1].length + ((4 - (match[1].length % 4)) % 4), "="));
    const domain = decoded.replace(/\$$/, "");
    if (!/^[a-z0-9.-]+$/i.test(domain)) return null;
    return `https://${domain}`;
  } catch {
    return null;
  }
}

/** Clerk-hosted origins a post-sign-in redirect may target. */
export function clerkTrustedOrigins(publishableKey: string | undefined): string[] {
  const fapi = clerkFrontendApiOrigin(publishableKey);
  if (!fapi) return [];
  const host = fapi.slice("https://".length);
  const origins = [fapi];
  if (host.endsWith(".clerk.accounts.dev")) {
    origins.push(`https://${host.replace(".clerk.accounts.dev", ".accounts.dev")}`);
  } else if (host.startsWith("clerk.")) {
    origins.push(`https://accounts.${host.slice("clerk.".length)}`);
  }
  return origins;
}

export function resolvePostSignInRedirect(
  search: string,
  options: { publishableKey?: string; fallback?: string } = {},
): string {
  const fallback = options.fallback ?? DEFAULT_POST_SIGN_IN_PATH;
  let target: string | null;
  try {
    target = new URLSearchParams(search).get("redirect_url");
  } catch {
    return fallback;
  }
  if (!target) return fallback;
  target = target.trim();

  // Same-origin path: "/x" but not protocol-relative "//evil".
  if (target.startsWith("/") && !target.startsWith("//") && !target.startsWith("/\\")) {
    return target;
  }

  const trusted = clerkTrustedOrigins(options.publishableKey).map((o) => o.toLowerCase());
  if (!trusted.length) return fallback;
  try {
    const url = new URL(target);
    if (url.protocol === "https:" && trusted.includes(url.origin.toLowerCase())) return url.toString();
  } catch {
    // not an absolute URL
  }
  return fallback;
}

/** Browser convenience: resolve from the current location. */
export function currentPostSignInRedirect(fallback?: string): string {
  if (typeof window === "undefined") return fallback ?? DEFAULT_POST_SIGN_IN_PATH;
  return resolvePostSignInRedirect(window.location.search, {
    publishableKey: process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
    fallback,
  });
}
