// Screenshot the /chats reader with the demo thread open.
import { chromium } from "playwright";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
await page.goto("http://localhost:3200/chats?thread=demo-thread-1", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
// expand one tool call for the shot
const tool = page.locator(".ev-tool-name.mcp", { hasText: "analyze_grain" }).first();
if (await tool.count()) await tool.click();
await page.waitForTimeout(400);
await page.screenshot({ path: "e2e-chats-page.png" });
await browser.close();
console.log("done");
