// Screenshot the knowledge retrieval heat-map view.
import { chromium } from "playwright";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto("http://localhost:3200/knowledge", { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
await page.click("text=Retrieval heat");
await page.waitForTimeout(2000);
await page.screenshot({ path: "e2e-heatmap.png", fullPage: false });
await browser.close();
console.log("done");
