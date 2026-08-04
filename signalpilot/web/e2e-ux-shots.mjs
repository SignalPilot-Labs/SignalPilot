import { chromium } from "playwright";
const pages = [
  ["dashboard", "/dashboard"],
  ["connections", "/connections"],
  ["query", "/query"],
  ["schema", "/schema"],
  ["audit", "/audit"],
  ["settings", "/settings"],
  ["integrations", "/integrations"],
  ["health", "/health"],
];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
for (const [name, path] of pages) {
  await page.goto(`http://localhost:3200${path}`, { waitUntil: "networkidle" }).catch(() => {});
  await page.waitForTimeout(1800);
  await page.screenshot({ path: `e2e-ux-${name}.png` });
  console.log("shot", name);
}
await browser.close();
