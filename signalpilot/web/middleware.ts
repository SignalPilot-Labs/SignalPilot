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
// Nonce generation — edge-runtime-safe (no Node crypto.randomBytes)
// ---------------------------------------------------------------------------

function generateNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  // btoa-safe: convert bytes to a binary string then base64-encode
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

// ---------------------------------------------------------------------------
// Security header helper — applied in BOTH paths
// ---------------------------------------------------------------------------

function applySecurityHeaders(
  response: NextResponse,
  withClerk: boolean,
  request: NextRequest,
  nonce: string
): void {
  const gatewayUrl =
    process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300";

  let connectSrc = `'self' ${gatewayUrl}`;
  // CSP script-src: nonce + strict-dynamic for modern browsers.
  // 'unsafe-inline' is kept as fallback because Next.js injects inline scripts
  // for hydration/chunk preloading that don't carry the nonce. Browsers that
  // support 'strict-dynamic' IGNORE 'unsafe-inline' (per CSP spec), so modern
  // browsers get nonce-only enforcement. 'unsafe-eval' is removed entirely.
  let scriptSrc = `'self' 'unsafe-inline' 'nonce-${nonce}' 'strict-dynamic'`;
  let imgSrc = "'self' data: blob:";
  // Fix JetBrains Mono CSP bug: cdn.jsdelivr.net was not in font-src
  const fontSrc = "'self' data: https://cdn.jsdelivr.net";

  let workerSrc = "'self'";

  let frameSrc = "'self'";

  if (withClerk) {
    connectSrc +=
      " https://*.clerk.accounts.dev https://*.signalpilot.ai https://clerk-telemetry.com";
    // Explicit origins kept as fallback for browsers without strict-dynamic
    scriptSrc += " https://*.clerk.accounts.dev https://*.signalpilot.ai https://challenges.cloudflare.com";
    imgSrc += " https://img.clerk.com";
    workerSrc += " blob:";
    frameSrc += " https://challenges.cloudflare.com";
  }

  const backendUrl =
    process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
  connectSrc += ` ${backendUrl}`;

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

    const nonce = generateNonce();

    // Forward nonce to server components via request header
    const requestHeaders = new Headers(req.headers);
    requestHeaders.set("x-nonce", nonce);

    const response = NextResponse.next({
      request: { headers: requestHeaders },
    });
    applySecurityHeaders(response, true, req, nonce);
    return response;
  });
} else {
  middlewareExport = (req: NextRequest) => {
    const nonce = generateNonce();

    const requestHeaders = new Headers(req.headers);
    requestHeaders.set("x-nonce", nonce);

    const response = NextResponse.next({
      request: { headers: requestHeaders },
    });
    applySecurityHeaders(response, false, req, nonce);
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
