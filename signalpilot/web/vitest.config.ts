import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./notebook"),
      "~": path.resolve(__dirname, "."),
    },
  },
  test: {
    // DOM globals are required: sanitize-html.ts registers DOMPurify hooks
    // behind a `typeof document !== "undefined"` guard. jsdom (not happy-dom)
    // is the environment DOMPurify itself supports and tests against.
    environment: "jsdom",
    globals: false,
    include: ["notebook/**/*.test.ts", "notebook/**/*.test.tsx", "lib/**/*.test.ts"],
    // Playwright specs under e2e/ are run by `npx playwright test`, not vitest.
    exclude: ["node_modules/**", ".next/**", "e2e/**"],
  },
});
