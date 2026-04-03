import { test } from "@playwright/test";
import path from "path";

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "iphone14pro", width: 393, height: 852 },
  { name: "iphoneSE", width: 375, height: 667 },
  { name: "android", width: 412, height: 915 },
];

const PAGES = [
  { name: "main", path: "/" },
  { name: "settings", path: "/settings" },
];

for (const vp of VIEWPORTS) {
  for (const pg of PAGES) {
    test(`${vp.name} - ${pg.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(pg.path, { waitUntil: "domcontentloaded" });
      // Allow animations to settle
      await page.waitForTimeout(1000);
      // Try to dismiss onboarding modal if present
      const skipBtn = page.locator("text=Skip");
      if (await skipBtn.isVisible({ timeout: 500 }).catch(() => false)) {
        await skipBtn.click();
        await page.waitForTimeout(500);
      }
      await page.screenshot({
        path: path.join(__dirname, "screenshots", `${vp.name}-${pg.name}.png`),
        fullPage: true,
      });
    });
  }
}
