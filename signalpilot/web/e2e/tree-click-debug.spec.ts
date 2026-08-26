import { test, expect } from "@playwright/test";

const PROJECT_ID = "3781d00d-3f10-4139-9b70-2e4cd9c42c63";

test("debug: tree folder expand", async ({ page }) => {
  test.setTimeout(120_000);

  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warn")
      console.log(`[${msg.type()}] ${msg.text().slice(0, 200)}`);
  });

  await page.goto(
    `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
    { waitUntil: "domcontentloaded" }
  );
  await page.locator(".sp-root").waitFor({ timeout: 60_000 });
  await page.locator(".cm-editor").first().waitFor({ timeout: 30_000 });
  await page.waitForTimeout(2000);

  // Open sidebar
  const strip = page.locator(".sp-root div[class*='flex'][class*='flex-col'][class*='bg-']").first();
  const icon = strip.locator("div[class*='rounded']").first();
  if (await icon.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await icon.click({ force: true });
  }

  // Wait for tree
  let treeCount = 0;
  for (let i = 0; i < 15; i++) {
    await page.waitForTimeout(2000);
    treeCount = await page.locator('[role="treeitem"]').count();
    if (treeCount > 0) break;
  }
  console.log(`Tree items: ${treeCount}`);

  // Find the "notebooks" treeitem and check its state
  const notebooksInfo = await page.evaluate(() => {
    const items = document.querySelectorAll('[role="treeitem"]');
    for (const item of items) {
      const span = item.querySelector("span.flex-1");
      if (span?.textContent?.trim() === "notebooks") {
        return {
          ariaExpanded: item.getAttribute("aria-expanded"),
          ariaLevel: item.getAttribute("aria-level"),
          innerHTML: (item as HTMLElement).innerHTML.slice(0, 200),
          offsetHeight: (item as HTMLElement).offsetHeight,
          offsetTop: (item as HTMLElement).offsetTop,
        };
      }
    }
    return null;
  });
  console.log("BEFORE click:", JSON.stringify(notebooksInfo, null, 2));

  // Method 1: Playwright force click on the row div
  console.log("\n--- Method 1: force click on div.cursor-pointer ---");
  const notebooksRow = page.locator('[role="treeitem"]').filter({
    has: page.locator('span.flex-1:text-is("notebooks")'),
  }).locator("div.cursor-pointer").first();
  await notebooksRow.click({ force: true });
  await page.waitForTimeout(3000);

  const afterForce = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('[role="treeitem"]')).map((el) => {
      const name = el.querySelector("span.flex-1")?.textContent?.trim();
      return `${name} (exp=${el.getAttribute("aria-expanded")}, lvl=${el.getAttribute("aria-level")})`;
    });
  });
  console.log("After force click:", afterForce.join(", "));

  // Method 2: Playwright force click on the treeitem itself
  console.log("\n--- Method 2: force click on [role=treeitem] ---");
  const notebooksItem = page.locator('[role="treeitem"]').filter({
    has: page.locator('span.flex-1:text-is("notebooks")'),
  }).first();
  await notebooksItem.click({ force: true });
  await page.waitForTimeout(3000);

  const afterTreeitem = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('[role="treeitem"]')).map((el) => {
      const name = el.querySelector("span.flex-1")?.textContent?.trim();
      return `${name} (exp=${el.getAttribute("aria-expanded")}, lvl=${el.getAttribute("aria-level")})`;
    });
  });
  console.log("After treeitem click:", afterTreeitem.join(", "));

  // Method 3: Playwright force click on the chevron SVG
  console.log("\n--- Method 3: force click on chevron SVG ---");
  const chevron = page.locator('[role="treeitem"]').filter({
    has: page.locator('span.flex-1:text-is("notebooks")'),
  }).locator("svg.lucide-chevron-right").first();
  if (await chevron.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await chevron.click({ force: true });
    await page.waitForTimeout(3000);
    const afterChevron = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('[role="treeitem"]')).map((el) => {
        const name = el.querySelector("span.flex-1")?.textContent?.trim();
        return `${name} (exp=${el.getAttribute("aria-expanded")}, lvl=${el.getAttribute("aria-level")})`;
      });
    });
    console.log("After chevron click:", afterChevron.join(", "));
  } else {
    console.log("Chevron not visible");
  }

  await page.waitForTimeout(3000);

  const finalNames = await page.evaluate(() => {
    const items = document.querySelectorAll('[role="treeitem"]');
    return Array.from(items).map((item) => {
      const span = item.querySelector("span.flex-1");
      return `${span?.textContent?.trim()} (exp=${item.getAttribute("aria-expanded")}, lvl=${item.getAttribute("aria-level")})`;
    });
  });
  console.log("FINAL state:", finalNames.join("\n  "));

  await page.screenshot({ path: "e2e-tree-debug.png" });
});
