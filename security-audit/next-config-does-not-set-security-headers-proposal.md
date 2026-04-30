# `next.config.ts` only sets `poweredByHeader: false`; missing other hardening

- Slug: next-config-does-not-set-security-headers
- Severity: Info
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/web/next.config.ts`

Back to [issues.md](issues.md)

---

## Problem

`next.config.ts` contains minimal configuration:

```typescript
// next.config.ts
const nextConfig: NextConfig = {
  poweredByHeader: false,
};
```

The following security hardening options are absent:

1. **`headers()` block**: No HSTS preload, no COOP/COEP headers via `next.config.ts`. (Some headers are set in `middleware.ts` but only HSTS, not COOP/COEP.)
2. **`images.remotePatterns`**: No image domain allowlist. Any domain can be used in `next/image` `src` (or the default Next.js image optimizer is unconfigured, allowing SSRF via the image proxy).
3. **`experimental.serverActions.allowedOrigins`**: Server Actions accept requests from any origin by default. Without an explicit allowlist, cross-origin Server Action calls are possible.
4. **`experimental.allowedRevalidateHeaderKeys`**: Not set — minor issue.

The most significant of these is the absence of `serverActions.allowedOrigins` and the image domain allowlist.

---

## Impact

- **Server Actions CSRF:** Without `serverActions.allowedOrigins`, a cross-origin attacker can trigger Server Actions from another site if the user is authenticated. (Mitigated in part by Clerk's CSRF protection, but defense-in-depth is missing.)
- **Image proxy SSRF:** If `next/image` is used with user-supplied URLs and no `remotePatterns` allowlist, the Next.js image optimizer can be used as a proxy to internal network resources.
- **Missing COOP/COEP:** Without `Cross-Origin-Opener-Policy` and `Cross-Origin-Embedder-Policy`, the app cannot use `SharedArrayBuffer` (less of a concern) and is more vulnerable to cross-origin attacks like Spectre.

---

## Affected surface

- Files: `signalpilot/web/next.config.ts`
- Endpoints: All Next.js pages and API routes
- Auth modes: Both cloud and local

---

## Proposed fix

```typescript
// next.config.ts:
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,

  // Lock image optimization to known safe domains
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "img.clerk.com" },
      { protocol: "https", hostname: "*.signalpilot.ai" },
    ],
  },

  // Restrict Server Actions to same origin
  experimental: {
    serverActions: {
      allowedOrigins: [
        "signalpilot.ai",
        "www.signalpilot.ai",
        "localhost:3200",
        "localhost:3000",
      ],
    },
  },

  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          // HSTS with preload (supplement middleware.ts which sets this conditionally)
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
          // Cross-Origin Opener Policy
          {
            key: "Cross-Origin-Opener-Policy",
            value: "same-origin",
          },
          // Permissions Policy (moved from middleware.ts for SSR pages)
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
```

---

## Verification / test plan

**Tests:**
1. `test_next_config_has_image_remote_patterns` — assert `images.remotePatterns` is set.
2. `test_next_config_server_actions_allowed_origins` — assert allowedOrigins matches expected list.

**Manual checklist:**
- Deploy to staging.
- Use `curl -I https://staging.signalpilot.ai/` and verify `Cross-Origin-Opener-Policy: same-origin` in response headers.
- Attempt `next/image` with an unauthorized domain — expect 400.

---

## Rollout / migration notes

- `allowedOrigins` must include all legitimate deployment domains. Test in staging.
- COOP `same-origin` may break cross-origin embeds or popups (e.g., Clerk's hosted UI modal). Test Clerk auth flows thoroughly.
- Rollback: revert `next.config.ts`.
