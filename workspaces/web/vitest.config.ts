import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./tests/setup.ts"],
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
      // server-only throws outside a Next.js server context; replace with a no-op in tests
      "server-only": fileURLToPath(new URL("./tests/__mocks__/server-only.ts", import.meta.url)),
    },
  },
});
