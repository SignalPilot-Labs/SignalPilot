// Screenshot the transcript slide-over: panel mode, then full-page mode.
import { chromium } from "playwright";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1680, height: 1200 } });
await page.goto("http://localhost:3200/evals?run=run-20260716-141321-3e8a85", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);

await page.click("table >> text=summit_charges");
await page.waitForTimeout(400);
await page.click("text=view full transcript");
await page.waitForTimeout(1800);
// open one sql tool call
const tool = page.locator(".tr-card-head .name.mcp", { hasText: "query_database" }).first();
if (await tool.count()) await tool.click();
await page.waitForTimeout(400);
await page.screenshot({ path: "e2e-transcript-panel.png" });

// expand to full page
await page.click('button[aria-label="expand"]');
await page.waitForTimeout(600);
await page.screenshot({ path: "e2e-transcript-full.png" });
await browser.close();
console.log("done");
