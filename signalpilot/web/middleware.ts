import { NextResponse } from "next/server";
import type { NextMiddleware, NextRequest } from "next/server";

/**
 * This Next.js middleware applies security headers and optional Clerk authentication.
 * It uses clerkMiddleware for session management when Clerk keys are available.
 * It applies only security headers when Clerk keys are absent.
 * The conditional import does not load @clerk/nextjs/server without CLERK_SECRET_KEY.
 */

const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";
const clerkEnabled = IS_CLOUD_MODE;

// The following function applies security headers to all request paths.

/**
 * Validate that a string contains a safe HTTP or HTTPS URL.
 * Reject characters that can add CSP directives through an environment variable.
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
// Notebook WebSocket connections to the gateway use ws or wss.
    try {
      const gwUrl = new URL(gatewayUrl);
      const wsScheme = gwUrl.protocol === "https:" ? "wss:" : "ws:";
      connectSrc += ` ${wsScheme}//${gwUrl.host}`;
    } catch {}
  } else {
    console.warn(`CSP: NEXT_PUBLIC_GATEWAY_URL is not a valid URL, omitting from connect-src: ${gatewayUrl}`);
  }
// Evaluation uploads send multipart PUT requests directly to S3.
// The connect-src directive includes the S3 origin. Local mode uses MinIO.
  const evalUploadsS3Origin =
    process.env.NEXT_PUBLIC_EVAL_UPLOADS_S3_ORIGIN ||
    (IS_CLOUD_MODE ? "https://s3.us-east-2.amazonaws.com" : "http://localhost:9000");
  if (isSafeUrl(evalUploadsS3Origin)) {
    connectSrc += ` ${evalUploadsS3Origin}`;
  }
// The script-src directive permits unsafe-inline for Next.js hydration and chunk preload scripts.
// These inline scripts cannot contain a nonce.
// The script-src directive permits unsafe-eval because Vega compiles expressions with new Function().
// Altair and Vega charts require this permission.
  let scriptSrc = "'self' 'unsafe-inline' 'unsafe-eval'";
  let imgSrc = `'self' data: blob: ${gatewayUrl}`;
  const fontSrc = "'self' data: https://cdn.jsdelivr.net";

  let workerSrc = "'self'";

// The frame-src directive always permits self.
// It also permits the gateway origin for a cross-origin gateway deployment.
// NEXT_PUBLIC_GATEWAY_URL is a build-time constant and does not use runtime API data.
  let frameSrc = "'self'";
  const gatewayOrigin = (() => {
    try {
      const u = new URL(gatewayUrl);
      return u.origin; // e.g. "http://localhost:3300"
    } catch {
      return null;
    }
  })();
// Development mode permits all localhost ports.
// Production mode permits only the configured gateway origin.
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

// The middleware export uses Clerk only when Clerk is enabled.
// Next.js 16 middleware supports top-level await in the edge runtime.
// The conditional import skips @clerk/nextjs/server when Clerk is disabled.

// The following function rewrites /notebook/* requests to the gateway.

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300";
const NOTEBOOK_PROXY_TARGET_URL =
  process.env.SP_GATEWAY_INTERNAL_URL || GATEWAY_URL;

function isNotebookPath(pathname: string): boolean {
  return pathname.startsWith("/notebook/");
}

function proxyNotebook(req: NextRequest): NextResponse {
  const target = new URL(
    req.nextUrl.pathname + req.nextUrl.search,
    NOTEBOOK_PROXY_TARGET_URL,
  );
  return NextResponse.rewrite(target, {
    headers: req.headers,
  });
}

// The following constant exports the middleware.

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
    "/notebook(.*)",
  ]);

  middlewareExport = clerkMiddleware(async (auth, req) => {
// The gateway authenticates proxied notebook paths without Clerk middleware.
    if (isNotebookPath(req.nextUrl.pathname)) {
      return proxyNotebook(req);
    }

    const { userId } = await auth();

    if (IS_CLOUD_MODE && !isPublicRoute(req) && !userId) {
      await auth.protect();
    }

    const response = NextResponse.next();
    applySecurityHeaders(response, true, req);
    return response;
  });
} else {
  middlewareExport = (req: NextRequest) => {
// Proxy notebook paths to the gateway.
    if (isNotebookPath(req.nextUrl.pathname)) {
      return proxyNotebook(req);
    }

    const response = NextResponse.next();
    applySecurityHeaders(response, false, req);
    return response;
  };
}

export default middlewareExport;

export const config = {
  matcher: [
// Include notebook static assets such as fonts and JavaScript chunks.
    "/notebook/:path*",
// Skip Next.js internal paths and static files.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
// Run the middleware for all API routes.
    "/(api|trpc)(.*)",
  ],
};
