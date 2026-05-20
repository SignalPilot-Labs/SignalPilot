import { NextResponse } from "next/server";
import type { NextMiddleware, NextRequest } from "next/server";

/**
 * Next.js middleware — security headers + optional Clerk auth.
 *
 * When Clerk keys are present (cloud mode or local-with-keys), routes through
 * clerkMiddleware for session management. When absent, applies security headers
 * only. The conditional dynamic import avoids loading @clerk/nextjs/server
 * when CLERK_SECRET_KEY is absent — clerkMiddleware() will throw without it.
 */

const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";
const clerkEnabled = IS_CLOUD_MODE;

// ---------------------------------------------------------------------------
// Security header helper — applied in BOTH paths
// ---------------------------------------------------------------------------

/**
 * Validate that a string is a safe URL (http: or https: protocol, no injection chars).
 * Prevents a compromised env var from injecting arbitrary CSP directives.
 */
function isSafeUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return ["http:", "https:"].includes(parsed.protocol);
  } catch {
    return false;
  }
}

function applySecurityHeaders(
  response: NextResponse,
  withClerk: boolean,
  request: NextRequest
): void {
  const gatewayUrl =
    process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300";

  let connectSrc = "'self'";
  if (isSafeUrl(gatewayUrl)) {
    connectSrc += ` ${gatewayUrl}`;
  } else {
    console.warn(`CSP: NEXT_PUBLIC_GATEWAY_URL is not a valid URL, omitting from connect-src: ${gatewayUrl}`);
  }
  // CSP script-src: 'unsafe-inline' is required because Next.js injects inline
  // scripts for hydration/chunk preloading that cannot carry a nonce (the nonce
  // is generated in middleware but Next.js renders inline scripts at build time).
  // 'unsafe-eval' is REMOVED — this is the main XSS hardening win, blocking
  // eval(), new Function(), setTimeout(string), etc.
  let scriptSrc = process.env.NODE_ENV === "development"
    ? "'self' 'unsafe-inline' 'unsafe-eval'"
    : "'self' 'unsafe-inline'";
  let imgSrc = "'self' data: blob:";
  const fontSrc = "'self' data: https://cdn.jsdelivr.net";

  let workerSrc = "'self'";

  // frame-src: always allow 'self'. Add the gateway origin if it differs from
  // the web app origin (cross-origin gateway deployment). NEXT_PUBLIC_GATEWAY_URL
  // is a build-time constant — never sourced from a runtime API response so a
  // malicious script cannot swap it to a different origin.
  let frameSrc = "'self'";
  const gatewayOrigin = (() => {
    try {
      const u = new URL(gatewayUrl);
      return u.origin; // e.g. "http://localhost:3300"
    } catch {
      return null;
    }
  })();
  // Include localhost wildcard for dev convenience only — in production the
  // gatewayOrigin covers the exact gateway host and there is no need to allow
  // arbitrary localhost ports. L-1: gate on NODE_ENV to avoid widening frame-src
  // in production builds.
  if (process.env.NODE_ENV === "development") {
    frameSrc += " http://localhost:* https://localhost:*";
  }
  if (gatewayOrigin && isSafeUrl(gatewayUrl) && gatewayOrigin !== "null") {
    frameSrc += ` ${gatewayOrigin}`;
  }

  if (withClerk) {
    connectSrc +=
      " https://*.clerk.accounts.dev https://*.signalpilot.ai https://clerk-telemetry.com";
    scriptSrc += " https://*.clerk.accounts.dev https://*.signalpilot.ai https://challenges.cloudflare.com";
    imgSrc += " https://img.clerk.com";
    workerSrc += " blob:";
    frameSrc += " https://challenges.cloudflare.com";
  }

  const backendUrl =
    process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
  if (isSafeUrl(backendUrl)) {
    connectSrc += ` ${backendUrl}`;
  } else {
    console.warn(`CSP: NEXT_PUBLIC_BACKEND_URL is not a valid URL, omitting from connect-src: ${backendUrl}`);
  }

  response.headers.set(
    "Content-Security-Policy",
    [
      "default-src 'self'",
      `connect-src ${connectSrc}`,
      `script-src ${scriptSrc}`,
      `worker-src ${workerSrc}`,
      "style-src 'self' 'unsafe-inline'",
      `img-src ${imgSrc}`,
      `font-src ${fontSrc}`,
      `frame-src ${frameSrc}`,
      "object-src 'none'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; ")
  );

  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-XSS-Protection", "0");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=(), interest-cohort=()"
  );

  if (request.headers.get("x-forwarded-proto") === "https") {
    response.headers.set(
      "Strict-Transport-Security",
      "max-age=63072000; includeSubDomains"
    );
  }
}

// ---------------------------------------------------------------------------
// Middleware export — conditional on Clerk being enabled.
// Top-level await works in Next.js 16 middleware (edge runtime).
// When clerkEnabled is false, the dynamic import is skipped entirely,
// so @clerk/nextjs/server is never loaded and CLERK_SECRET_KEY is not needed.
// ---------------------------------------------------------------------------

let middlewareExport: NextMiddleware;

if (clerkEnabled) {
  const { clerkMiddleware, createRouteMatcher } = await import(
    "@clerk/nextjs/server"
  );

  const isPublicRoute = createRouteMatcher([
    "/sign-in(.*)",
    "/sign-up(.*)",
    "/onboarding(.*)",
    "/",
  ]);

  middlewareExport = clerkMiddleware(async (auth, req) => {
    const { userId } = await auth();

    // In cloud mode, protect non-public routes (unauthenticated users only)
    if (IS_CLOUD_MODE && !isPublicRoute(req) && !userId) {
      await auth.protect();
    }

    const response = NextResponse.next();
    applySecurityHeaders(response, true, req);
    return response;
  });
} else {
  middlewareExport = (req: NextRequest) => {
    const response = NextResponse.next();
    applySecurityHeaders(response, false, req);
    return response;
  };
}

export default middlewareExport;

export const config = {
  matcher: [
    // Skip Next.js internals and all static files (Clerk-recommended pattern)
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    // Always run for API routes
    "/(api|trpc)(.*)",
  ],
};
