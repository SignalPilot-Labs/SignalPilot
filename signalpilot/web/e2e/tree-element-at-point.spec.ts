import { test } from "@playwright/test";

const PROJECT_ID = "3781d00d-3f10-4139-9b70-2e4cd9c42c63";

test("what element is at the tree item coordinates?", async ({ page }) => {
  test.setTimeout(90_000);

  await page.goto(
    `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
    { waitUntil: "domcontentloaded" }
  );
  await page.locator(".sp-root").waitFor({ timeout: 60_000 });
  await page.locator(".cm-editor").first().waitFor({ timeout: 30_000 });
  await page.waitForTimeout(2000);

  // Open sidebar
  const strip = page.locator(".sp-root div[class*='flex'][class*='flex-col'][class*='bg-']").first();
  await strip.locator("div[class*='rounded']").first().click({ force: true });

  for (let i = 0; i < 15; i++) {
    await page.waitForTimeout(2000);
    if (await page.locator('[role="treeitem"]').count() > 0) break;
  }

  // Get the bounding box of the "notebooks" treeitem
  const result = await page.evaluate(() => {
    const items = document.querySelectorAll('[role="treeitem"]');
    for (const item of items) {
      const span = item.querySelector("span.flex-1");
      if (span?.textContent?.trim() === "notebooks") {
        const rect = (item as HTMLElement).getBoundingClientRect();
        // Use left side (20px in) to stay within the sidebar panel
        const centerX = rect.left + 20;
        const centerY = rect.top + rect.height / 2;

        // What element is actually at those coordinates?
        const elementAtPoint = document.elementFromPoint(centerX, centerY);

        // Walk up from the treeitem to find if it's the same element
        let isSameTree = false;
        let walker: Element | null = elementAtPoint;
        while (walker) {
          if (walker === item) { isSameTree = true; break; }
          walker = walker.parentElement;
        }

        // Get the ancestry of the element at point
        const ancestry: string[] = [];
        walker = elementAtPoint;
        let depth = 0;
        while (walker && depth < 10) {
          ancestry.push(`${walker.tagName}.${(walker.className || "").toString().slice(0, 40)} [${(walker as HTMLElement).style.cssText?.slice(0, 40) || ""}]`);
          walker = walker.parentElement;
          depth++;
        }

        return {
          treeitemRect: { x: Math.round(rect.left), y: Math.round(rect.top), w: Math.round(rect.width), h: Math.round(rect.height) },
          centerPoint: { x: Math.round(centerX), y: Math.round(centerY) },
          elementAtPoint: elementAtPoint ? `${elementAtPoint.tagName}.${(elementAtPoint.className || "").toString().slice(0, 50)}` : "null",
          elementAtPointText: elementAtPoint?.textContent?.trim().slice(0, 40),
          isSameTree,
          ancestry,
        };
      }
    }
    return { error: "notebooks not found" };
  });

  console.log("\n=== ELEMENT AT POINT ANALYSIS ===");
  console.log(JSON.stringify(result, null, 2));
});
