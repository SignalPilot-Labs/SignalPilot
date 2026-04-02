/**
 * Mobile Responsiveness Auto-Audit
 *
 * Screenshots every page and interactive state at mobile viewport sizes.
 * Run with: npx playwright test e2e/mobile-audit.spec.ts
 *
 * Screenshots are saved to e2e/screenshots/ for manual review.
 * Tests are designed to work without the backend API running.
 */
import { test, expect } from "@playwright/test";
import path from "path";
import fs from "fs";

const SCREENSHOT_DIR = path.join(__dirname, "screenshots");

// Ensure screenshot dir exists
fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

// Helper: take a named screenshot with project name prefix
async function snap(
  page: import("@playwright/test").Page,
  name: string,
  testInfo: import("@playwright/test").TestInfo,
) {
  const projectName = testInfo.project.name;
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, `${projectName}--${name}.png`),
    fullPage: true,
  });
}

// Helper: mock API responses so the app works without a backend
async function mockApi(page: import("@playwright/test").Page) {
  // The app calls port 3401 for API. Intercept all requests to that port.
  // Use a broad pattern that catches both same-origin and cross-origin calls.

  const mockResponses: Record<string, unknown> = {
    "/api/settings/status": {
      configured: true,
      has_claude_token: true,
      has_git_token: true,
      has_github_repo: true,
    },
    "/api/settings": {
      claude_token: "***",
      git_token: "***",
      github_repo: "acme/demo-project",
    },
    "/api/repos": [{ repo: "acme/demo-project", run_count: 3 }],
    "/api/agent/health": { status: "idle" },
  };

  const mockRuns = [
    {
      id: "demo-run-1",
      status: "completed",
      branch_name: "improvements-round-2026-04-01-abc123",
      started_at: new Date(Date.now() - 3600000).toISOString(),
      total_tool_calls: 42,
      total_cost_usd: 1.23,
      total_input_tokens: 150000,
      total_output_tokens: 50000,
      pr_url: null,
      error_message: null,
      rate_limit_resets_at: null,
    },
    {
      id: "demo-run-2",
      status: "running",
      branch_name: "improvements-round-2026-04-02-def456",
      started_at: new Date(Date.now() - 600000).toISOString(),
      total_tool_calls: 15,
      total_cost_usd: 0.45,
      total_input_tokens: 80000,
      total_output_tokens: 20000,
      pr_url: null,
      error_message: null,
      rate_limit_resets_at: null,
    },
  ];

  // Catch ALL requests (including cross-origin to port 3401)
  await page.route("**/*", (route) => {
    const url = route.request().url();

    // Only intercept API calls (to port 3401 or /api/ paths)
    if (!url.includes(":3401") && !url.includes("/api/")) {
      return route.continue();
    }

    // Block SSE/EventSource connections
    if (url.includes("/events/")) {
      return route.abort();
    }

    // Match specific API endpoints
    for (const [path, response] of Object.entries(mockResponses)) {
      if (url.includes(path)) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(response),
        });
      }
    }

    // Runs endpoint
    if (url.includes("/api/runs")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockRuns),
      });
    }

    // Branches
    if (url.includes("/api/branches")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(["main", "staging", "dev"]),
      });
    }

    // Parallel runs
    if (url.includes("/api/parallel")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ active: 0, max_concurrent: 4, slots: [] }),
      });
    }

    // Diff
    if (url.includes("/api/diff")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ files: [], total_files: 0, total_added: 0, total_removed: 0, source: "none" }),
      });
    }

    // Catch-all for any other API calls
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "[]",
    });
  });
}

// Helper: wait for page to settle (fonts, animations)
async function settle(page: import("@playwright/test").Page) {
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(1500);
}

// ─── Main Dashboard ────────────────────────────────────────────────

test.describe("Dashboard - Main Page", () => {
  test("renders without horizontal overflow", async ({ page }, testInfo) => {
    await mockApi(page);
    await page.goto("/");
    await settle(page);
    await snap(page, "01-dashboard-initial", testInfo);

    // Check no horizontal overflow
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    const viewportWidth = await page.evaluate(() => window.innerWidth);
    expect(bodyWidth).toBeLessThanOrEqual(viewportWidth + 1);
  });

  test("header elements are visible and not clipped", async ({ page }, testInfo) => {
    await mockApi(page);
    await page.goto("/");
    await settle(page);

    // Header should be visible (use CSS selector — getByRole("banner") is unreliable with route mocks)
    const header = page.locator("header").first();
    await expect(header).toBeVisible({ timeout: 10000 });

    // Logo image should be visible
    const logo = header.locator("img").first();
    await expect(logo).toBeVisible();

    // Header should not overflow
    const headerBox = await header.boundingBox();
    const viewport = page.viewportSize();
    if (headerBox && viewport) {
      expect(headerBox.width).toBeLessThanOrEqual(viewport.width + 1);
    }

    await snap(page, "02-dashboard-header", testInfo);
  });

  test("view toggle buttons work", async ({ page }, testInfo) => {
    await mockApi(page);
    await page.goto("/");
    await settle(page);

    // Click Bots tab
    const botsBtn = page.locator("header button").filter({ hasText: "Bots" }).first();
    if (await botsBtn.isVisible()) {
      await botsBtn.click();
      await page.waitForTimeout(300);
      await snap(page, "03-dashboard-bots-view", testInfo);
    }

    // Click Feed tab
    const feedBtn = page.locator("header button").filter({ hasText: "Feed" }).first();
    if (await feedBtn.isVisible()) {
      await feedBtn.click();
      await page.waitForTimeout(300);
      await snap(page, "04-dashboard-feed-view", testInfo);
    }
  });
});

// ─── Mobile Drawers ────────────────────────────────────────────────

test.describe("Mobile Drawers", () => {
  test("hamburger menu opens runs drawer", async ({ page }, testInfo) => {
    const viewport = page.viewportSize();
    if (viewport && viewport.width >= 768) {
      test.skip();
      return;
    }

    await mockApi(page);
    await page.goto("/");
    await settle(page);

    // Find hamburger button
    const hamburger = page.locator('button[aria-label="Toggle runs sidebar"]');
    if (await hamburger.isVisible({ timeout: 2000 }).catch(() => false)) {
      await hamburger.click();
      await page.waitForTimeout(400);
      await snap(page, "05-mobile-runs-drawer-open", testInfo);

      // The overlay should be visible
      const overlay = page.locator(".mobile-drawer-overlay");
      const overlayVisible = await overlay.isVisible().catch(() => false);
      expect(overlayVisible).toBeTruthy();

      // Close by clicking overlay
      if (overlayVisible) {
        await overlay.click({ position: { x: 10, y: 10 }, force: true });
        await page.waitForTimeout(400);
        await snap(page, "06-mobile-runs-drawer-closed", testInfo);
      }
    }
  });

  test("worktree drawer opens from feed view", async ({ page }, testInfo) => {
    const viewport = page.viewportSize();
    if (viewport && viewport.width >= 768) {
      test.skip();
      return;
    }

    await mockApi(page);
    await page.goto("/");
    await settle(page);

    // Switch to feed view first
    const feedBtn = page.locator("header button").filter({ hasText: "Feed" }).first();
    if (await feedBtn.isVisible()) {
      await feedBtn.click();
      await page.waitForTimeout(300);
    }

    // Worktree button only shows when a run is selected,
    // but we can still screenshot the feed view state
    await snap(page, "07-mobile-feed-view", testInfo);
  });
});

// ─── New Bot Modal ─────────────────────────────────────────────────

test.describe("New Bot Modal", () => {
  test("modal fits within viewport", async ({ page }, testInfo) => {
    await mockApi(page);
    await page.goto("/");
    await settle(page);

    // The "New Bot" button might be disabled if not configured,
    // but the "Setup Required" button should still be visible
    const newBotBtn = page.locator("header").getByRole("button").filter({ hasText: /New|Setup/i }).first();
    if (await newBotBtn.isVisible()) {
      // If enabled, click to open modal
      const disabled = await newBotBtn.isDisabled();
      if (!disabled) {
        await newBotBtn.click();
        await page.waitForTimeout(500);
        await snap(page, "08-new-bot-modal", testInfo);

        // Modal should not overflow viewport
        const modalEl = page.locator(".card-accent-top").first();
        if (await modalEl.isVisible().catch(() => false)) {
          const box = await modalEl.boundingBox();
          const viewport = page.viewportSize();
          if (box && viewport) {
            expect(box.width).toBeLessThanOrEqual(viewport.width);
            expect(box.x).toBeGreaterThanOrEqual(-1);
          }

          // Scroll to show quick prompts
          await modalEl.evaluate((el) => (el.scrollTop = 300));
          await page.waitForTimeout(200);
          await snap(page, "09-new-bot-modal-scrolled", testInfo);
        }
      } else {
        // Button disabled — just screenshot current state
        await snap(page, "08-new-bot-disabled", testInfo);
      }
    }
  });
});

// ─── Onboarding Modal ──────────────────────────────────────────────

test.describe("Onboarding Modal", () => {
  test("modal renders properly on mobile", async ({ page }, testInfo) => {
    // Mock API as unconfigured so onboarding modal appears
    await page.route("**/*", (route) => {
      const url = route.request().url();
      if (!url.includes(":3401") && !url.includes("/api/")) {
        return route.continue();
      }
      if (url.includes("/events/")) return route.abort();
      if (url.includes("/api/settings/status")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            configured: false,
            has_claude_token: false,
            has_git_token: false,
            has_github_repo: false,
          }),
        });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });

    await page.goto("/");
    await settle(page);

    // The onboarding modal auto-opens when unconfigured
    const modal = page.locator(".card-accent-top").first();
    if (await modal.isVisible({ timeout: 3000 }).catch(() => false)) {
      await snap(page, "10-onboarding-modal", testInfo);

      // Check it doesn't overflow
      const box = await modal.boundingBox();
      const viewport = page.viewportSize();
      if (box && viewport) {
        expect(box.width).toBeLessThanOrEqual(viewport.width);
      }
    }
  });
});

// ─── Settings Page ─────────────────────────────────────────────────

test.describe("Settings Page", () => {
  test("renders without horizontal overflow", async ({ page }, testInfo) => {
    await mockApi(page);
    await page.goto("/settings");
    await settle(page);
    await snap(page, "11-settings-page", testInfo);

    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    const viewportWidth = await page.evaluate(() => window.innerWidth);
    expect(bodyWidth).toBeLessThanOrEqual(viewportWidth + 1);
  });

  test("header and navigation visible", async ({ page }, testInfo) => {
    await mockApi(page);
    await page.goto("/settings");
    await settle(page);

    // The settings page has a "Dashboard" back link
    const backLink = page.locator('a[href="/"]');
    await expect(backLink.first()).toBeVisible();

    // "Settings" text should be visible
    const heading = page.locator("h1");
    await expect(heading.first()).toBeVisible();

    await snap(page, "12-settings-header", testInfo);
  });

  test("form fields do not overflow", async ({ page }, testInfo) => {
    await mockApi(page);
    await page.goto("/settings");
    await settle(page);

    // Check all visible inputs don't overflow
    const inputs = page.locator("input");
    const count = await inputs.count();
    const viewport = page.viewportSize();

    for (let i = 0; i < count; i++) {
      const input = inputs.nth(i);
      if (await input.isVisible()) {
        const box = await input.boundingBox();
        if (box && viewport) {
          expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 2);
        }
      }
    }
    await snap(page, "13-settings-form-fields", testInfo);
  });
});

// ─── Touch Target Audit ────────────────────────────────────────────

test.describe("Touch Target Sizes", () => {
  test("audit interactive element sizes", async ({ page }, testInfo) => {
    await mockApi(page);
    await page.goto("/");
    await settle(page);

    const buttons = page.locator("button, a[href]");
    const count = await buttons.count();
    const violations: string[] = [];

    for (let i = 0; i < Math.min(count, 30); i++) {
      const btn = buttons.nth(i);
      if (await btn.isVisible()) {
        const box = await btn.boundingBox();
        if (box && (box.width < 28 || box.height < 28)) {
          const text = (await btn.textContent().catch(() => ""))?.trim().slice(0, 30) || "";
          const label = (await btn.getAttribute("aria-label").catch(() => "")) || "";
          violations.push(
            `"${text || label || `button#${i}`}" is ${Math.round(box.width)}x${Math.round(box.height)}px`,
          );
        }
      }
    }

    // Log violations for review (informational, not hard-fail)
    if (violations.length > 0) {
      console.log(`\nTouch target warnings (${violations.length}):`);
      violations.forEach((v) => console.log(`  - ${v}`));
    }

    await snap(page, "14-touch-targets-audit", testInfo);
  });
});

// ─── Full Page Screenshot Matrix ───────────────────────────────────

test.describe("Screenshot Matrix", () => {
  const routes = [
    { name: "dashboard", url: "/" },
    { name: "settings", url: "/settings" },
  ];

  for (const route of routes) {
    test(`full page: ${route.name}`, async ({ page }, testInfo) => {
      await mockApi(page);
      await page.goto(route.url);
      await settle(page);
      await snap(page, `matrix-${route.name}`, testInfo);
    });
  }
});
