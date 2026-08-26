// Dump the visible transcript turn heads for debugging.
import { chromium } from "playwright";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1680, height: 1200 } });
await page.goto("http://localhost:3200/evals?run=run-20260716-141321-3e8a85", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
await page.click("table >> text=summit_charges");
await page.waitForTimeout(400);
await page.click("text=view full transcript");
await page.waitForTimeout(1800);

const items = await page.locator(".ev-panel .tr-item").evaluateAll((els) =>
  els.map((el) => el.textContent?.replace(/\s+/g, " ").slice(0, 120)),
);
console.log(items.join("\n"));
await browser.close();
