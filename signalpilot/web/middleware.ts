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

function applySecurityHeaders(
  response: NextResponse,
  withClerk: boolean
): void {
  const gatewayUrl =
    process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300";

  let connectSrc = `'self' ${gatewayUrl}`;
  let scriptSrc = "'self' 'unsafe-inline' 'unsafe-eval'";
  let imgSrc = "'self' data: blob:";
  // Fix JetBrains Mono CSP bug: cdn.jsdelivr.net was not in font-src
  const fontSrc = "'self' data: https://cdn.jsdelivr.net";

  let workerSrc = "'self'";

  if (withClerk) {
    connectSrc +=
      " https://*.clerk.accounts.dev https://clerk-telemetry.com";
    scriptSrc += " https://*.clerk.accounts.dev";
    imgSrc += " https://img.clerk.com";
    workerSrc += " blob:";
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
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; ")
  );

  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-XSS-Protection", "1; mode=block");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=(), interest-cohort=()"
  );
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
    "/",
  ]);

  middlewareExport = clerkMiddleware(async (auth, req) => {
    // In cloud mode, protect all non-public routes
    if (IS_CLOUD_MODE && !isPublicRoute(req)) {
      await auth.protect();
    }
    const response = NextResponse.next();
    applySecurityHeaders(response, true);
    return response;
  });
} else {
  middlewareExport = (_req: NextRequest) => {
    const response = NextResponse.next();
    applySecurityHeaders(response, false);
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
