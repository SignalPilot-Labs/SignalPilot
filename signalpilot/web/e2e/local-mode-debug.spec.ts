import { test } from "@playwright/test";

test("Local mode debug: log ALL errors", async ({ page }) => {
  test.setTimeout(120_000);

  const errors: string[] = [];
  const networkErrors: string[] = [];

  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warn") {
      errors.push(`[${msg.type()}] ${msg.text().slice(0, 300)}`);
    }
  });
  page.on("pageerror", (err) => {
    errors.push(`[PAGE_ERROR] ${err.message.slice(0, 300)}`);
  });
  page.on("response", (resp) => {
    if (resp.status() >= 400) {
      networkErrors.push(`${resp.status()} ${resp.request().method()} ${resp.url().slice(0, 120)}`);
    }
  });

  console.log("=== Navigating to /projects ===");
  await page.goto("/projects", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(5000);

  // Click Open IDE if visible
  const openBtn = page.getByRole("button", { name: /open ide/i });
  if (await openBtn.isVisible({ timeout: 5_000 }).catch(() => false)) {
    console.log("Clicking Open IDE...");
    await openBtn.click();
    await page.waitForTimeout(10000);
  }

  // Wait for .sp-root
  const hasSpRoot = await page.locator(".sp-root").isVisible({ timeout: 30_000 }).catch(() => false);
  console.log(`sp-root visible: ${hasSpRoot}`);
  await page.waitForTimeout(10000);

  // Take screenshot
  await page.screenshot({ path: "e2e-local-debug.png" });

  // Print ALL errors
  console.log("\n=== CONSOLE ERRORS/WARNINGS ===");
  for (const e of errors) {
    console.log(`  ${e}`);
  }

  console.log("\n=== HTTP ERRORS (4xx/5xx) ===");
  for (const e of networkErrors) {
    console.log(`  ${e}`);
  }

  console.log(`\nTotal console errors: ${errors.length}`);
  console.log(`Total HTTP errors: ${networkErrors.length}`);
});
