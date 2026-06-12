import { test } from "@playwright/test";

const PROJECT_ID = "3781d00d-3f10-4139-9b70-2e4cd9c42c63";

test("debug: tree container height and click target", async ({ page }) => {
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

  // Wait for tree
  for (let i = 0; i < 15; i++) {
    await page.waitForTimeout(2000);
    if (await page.locator('[role="treeitem"]').count() > 0) break;
  }

  // Check ALL container heights in the tree ancestry
  const heights = await page.evaluate(() => {
    const treeItem = document.querySelector('[role="treeitem"]');
    if (!treeItem) return { error: "no treeitem" };

    const result: Record<string, string> = {};
    let el: HTMLElement | null = treeItem as HTMLElement;
    let depth = 0;
    while (el && depth < 15) {
      const rect = el.getBoundingClientRect();
      const styles = getComputedStyle(el);
      result[`${depth}_${el.tagName}.${(el.className || "").toString().slice(0, 30)}`] =
        `${Math.round(rect.width)}x${Math.round(rect.height)} pos=${styles.position} overflow=${styles.overflow} pe=${styles.pointerEvents}`;
      el = el.parentElement;
      depth++;
    }

    // Also check the tree's virtual list container
    const virtualList = document.querySelector('[role="treeitem"]')?.parentElement;
    if (virtualList) {
      result["virtualList"] = `${virtualList.tagName} ${virtualList.style.height} offsetH=${(virtualList as HTMLElement).offsetHeight}`;
    }

    return result;
  });

  console.log("\n=== TREE CONTAINER HIERARCHY ===");
  for (const [k, v] of Object.entries(heights)) {
    console.log(`  ${k}: ${v}`);
  }

  // Check if the tree has any event listeners
  const eventInfo = await page.evaluate(() => {
    const treeItem = document.querySelector('[role="treeitem"]');
    const row = treeItem?.querySelector("div.cursor-pointer");
    if (!row) return "no row found";

    // Check if react has fiber attached
    const fiberKey = Object.keys(row).find(k => k.startsWith("__reactFiber") || k.startsWith("__reactInternalInstance"));
    const propsKey = Object.keys(row).find(k => k.startsWith("__reactProps") || k.startsWith("__reactEvents"));

    return {
      hasFiber: !!fiberKey,
      hasProps: !!propsKey,
      propsKey: propsKey || "none",
      rowKeys: Object.keys(row).filter(k => k.startsWith("__")).join(", "),
    };
  });

  console.log("\n=== REACT EVENT BINDING ===");
  console.log(JSON.stringify(eventInfo, null, 2));
});
