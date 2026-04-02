import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for mobile responsiveness audit.
 * All projects use Chromium with different viewport/device emulation sizes.
 */
export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/results",
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: "http://localhost:3400",
    screenshot: "on",
    trace: "off",
    // Force Chromium for all projects (WebKit/Firefox may not be installed)
    browserName: "chromium",
  },
  projects: [
    {
      name: "mobile-375",
      use: {
        viewport: { width: 375, height: 812 },
        isMobile: true,
        hasTouch: true,
        userAgent: devices["iPhone 12"].userAgent,
      },
    },
    {
      name: "mobile-320",
      use: {
        viewport: { width: 320, height: 568 },
        isMobile: true,
        hasTouch: true,
        userAgent: devices["iPhone SE"].userAgent,
      },
    },
    {
      name: "mobile-393",
      use: {
        viewport: { width: 393, height: 851 },
        isMobile: true,
        hasTouch: true,
        userAgent: devices["Pixel 5"].userAgent,
      },
    },
    {
      name: "tablet-768",
      use: {
        viewport: { width: 768, height: 1024 },
        isMobile: false,
        hasTouch: true,
      },
    },
    {
      name: "desktop-1024",
      use: {
        viewport: { width: 1024, height: 768 },
        isMobile: false,
        hasTouch: false,
      },
    },
  ],
  webServer: {
    command: "npm run dev",
    port: 3400,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
