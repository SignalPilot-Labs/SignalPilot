/**
 * Centralised build-environment accessors.
 *
 * Replaces all `import.meta.env.*` call sites so Next.js / Turbopack can
 * statically inline `process.env.NODE_ENV` at build time.  Vite also handles
 * `process.env.NODE_ENV`, so this module is safe for both build systems and
 * for vitest (NODE_ENV=test).
 *
 * VITEST detection uses the well-known `__vitest_worker__` global injected by
 * vitest's worker thread bootstrap — same technique used by `@testing-library`.
 */
export const BUILD_ENV = {
  DEV: process.env.NODE_ENV !== "production",
  PROD: process.env.NODE_ENV === "production",
  MODE: process.env.NODE_ENV ?? "development",
  VITEST:
    typeof (globalThis as { __vitest_worker__?: unknown }).__vitest_worker__ !==
    "undefined",
  SP_VERSION: process.env.NEXT_PUBLIC_SP_VERSION ?? "dev",
} as const;
