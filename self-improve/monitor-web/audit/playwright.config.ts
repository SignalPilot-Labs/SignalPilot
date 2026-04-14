import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  outputDir: "./screenshots",
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:3400",
    screenshot: "on",
  },
  reporter: [["list"]],
});
