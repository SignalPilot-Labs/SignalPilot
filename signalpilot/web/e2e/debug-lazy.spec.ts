import { test } from "@playwright/test";

const URL = "/projects?project=3781d00d-3f10-4139-9b70-2e4cd9c42c63&branch=main&file=intro.py";

test("debug lazy requests", async ({ page }) => {
  test.setTimeout(30_000);

  const t0 = Date.now();
  const ts = (l: string) => console.log(`[${((Date.now() - t0) / 1000).toFixed(2)}s] ${l}`);

  let logCount = 0;
  page.on("console", (msg) => {
    logCount++;
    const t = msg.text();
    if (t.includes("[lazy-req]") || t.includes("Runtime") || t.includes("lazy") || t.includes("sendListFiles")) {
      ts(`[${msg.type()}] ${t.slice(0, 200)}`);
    }
  });
  page.on("pageerror", (err) => ts(`PAGE_ERROR: ${err.message.slice(0, 200)}`));

  ts("navigate");
  await page.goto(URL, { waitUntil: "domcontentloaded" });
  ts("DOMContentLoaded");

  // Check what rendered
  await page.waitForTimeout(3000);
  const hasSpRoot = await page.locator(".sp-root").isVisible().catch(() => false);
  const hasRunning = await page.getByText("running").isVisible().catch(() => false);
  const hasOpenIde = await page.getByRole("button", { name: /open ide/i }).isVisible().catch(() => false);
  ts(`state: sp-root=${hasSpRoot} running=${hasRunning} openIde=${hasOpenIde} totalLogs=${logCount}`);

  await page.waitForTimeout(10_000);
  ts(`after 10s wait: totalLogs=${logCount}`);

  await page.screenshot({ path: "e2e-debug-lazy.png" });
});
