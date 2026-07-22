// Screenshot the run detail: verdict chips, answer, and transcript viewer.
import { chromium } from "playwright";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });
await page.goto("http://localhost:3200/evals?run=run-20260716-141321-3e8a85", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);

// expand the question row, then the transcript
await page.click("table >> text=summit_charges");
await page.waitForTimeout(500);
await page.click("text=view full transcript");
await page.waitForTimeout(1500);
// expand the first sp tool call
const tool = page.locator(".ev-tool-name.mcp").first();
if (await tool.count()) await tool.click();
await page.waitForTimeout(400);
const run = page.locator(".ev-card", { hasText: "run-20260716-141321" }).first();
await run.screenshot({ path: "e2e-evals-v2-run.png" });
await browser.close();
console.log("done");
