import { test } from "@playwright/test";

const PROJECT = "c90eacbf-3f69-45d3-a7e9-2bff3266ede7";
const URL = `/projects?project=${PROJECT}&branch=main&file=intro.py`;

test("timing breakdown — where does the time go on a hot pod", async ({ page }) => {
  test.setTimeout(120_000);

  const t0 = Date.now();
  const ts = (label: string) => console.log(`[${((Date.now() - t0) / 1000).toFixed(2)}s] ${label}`);

  page.on("console", (msg) => {
    const t = msg.text();
    if (t.includes("[Sync]") || t.includes("[sync-gate]") || t.includes("Runtime")) {
      ts(`BROWSER: ${t}`);
    }
  });
  page.on("response", (r) => {
    const u = r.url();
    if (u.includes("localhost:3300/notebook")) {
      ts(`<< ${r.status()} ${r.request().method()} ${u.replace(/http:\/\/localhost:3300\/notebook\/[^/]+/, "")}`);
    }
  });

  ts("navigating...");
  await page.goto(URL);
  ts("DOMContentLoaded");

  // Wait for embed to appear
  await page.locator(".sp-root").waitFor({ timeout: 30_000 });
  ts(".sp-root attached");

  // Wait for kernel instantiate
  const inst = page.waitForResponse(
    (r) => r.url().includes("/kernel/instantiate"),
    { timeout: 60_000 }
  ).catch(() => null);

  const resp = await inst;
  ts(resp ? `kernel/instantiate ${resp.status()}` : "kernel/instantiate not called");

  // Wait for file content
  await page.waitForTimeout(5000);
  const text = await page.locator(".sp-root").innerText().catch(() => "");
  ts(text.includes("Welcome") || text.includes("import") ? "file content visible" : "no file content");
});
