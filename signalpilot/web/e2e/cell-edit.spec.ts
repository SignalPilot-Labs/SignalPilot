import { test, expect } from "@playwright/test";

test("CodeMirror cell editing works", async ({ page }) => {
  test.setTimeout(180_000);

  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });

  await page.goto(
    "/projects?project=3781d00d-3f10-4139-9b70-2e4cd9c42c63&branch=main&file=notebooks%2Fintro.py",
    { waitUntil: "domcontentloaded" }
  );

  // Wait for notebook to fully load (cold start can take 60-90s)
  console.log("Waiting for .sp-root...");
  await page.locator(".sp-root").waitFor({ timeout: 120_000 });
  console.log("sp-root visible, waiting for cm-editor...");
  await page.locator(".cm-editor").first().waitFor({ timeout: 60_000 });
  console.log("cm-editor found, waiting for styles to settle...");
  await page.waitForTimeout(3000);

  // ─── Check: styles loaded ──────────────────────────────────
  const cmRuleCount = await page.evaluate(() => {
    let count = 0;
    for (const sheet of document.styleSheets) {
      try {
        for (const rule of sheet.cssRules) {
          if (rule.cssText.includes(".cm-") || rule.cssText.includes(".ͼ")) count++;
        }
      } catch {}
    }
    return count;
  });
  console.log(`CM CSS rules: ${cmRuleCount}`);
  expect(cmRuleCount).toBeGreaterThan(50);

  // ─── Check: cursor visible after click ─────────────────────
  const cmContent = page.locator(".cm-editor").first().locator(".cm-content");
  await cmContent.click();
  await page.waitForTimeout(500);

  const cursorInfo = await page.evaluate(() => {
    const cursors = document.querySelectorAll(".cm-cursor, .cm-cursor-primary, .cm-cursorLayer");
    const drawSelection = document.querySelector(".cm-selectionLayer, .cm-cursorLayer");
    const focused = document.querySelector(".cm-focused");
    return {
      cursorElements: cursors.length,
      hasDrawSelection: !!drawSelection,
      hasFocused: !!focused,
      activeElement: document.activeElement?.className?.toString().slice(0, 60),
    };
  });
  console.log("\nCursor info:", JSON.stringify(cursorInfo, null, 2));

  // ─── Check: typing inserts at cursor position ──────────────
  await page.keyboard.press("End");
  await page.waitForTimeout(200);

  const beforeType = await page.evaluate(() => {
    const line = document.querySelector(".cm-editor .cm-line");
    return line?.textContent ?? "";
  });
  console.log(`\nFirst line before: "${beforeType}"`);

  await page.keyboard.type("TESTINPUT");
  await page.waitForTimeout(300);

  const afterType = await page.evaluate(() => {
    const lines = document.querySelectorAll(".cm-editor:first-of-type .cm-line");
    const texts: string[] = [];
    lines.forEach((l) => texts.push(l.textContent ?? ""));
    return texts;
  });
  console.log(`Lines after typing:`, afterType.slice(0, 5));

  const contentText = afterType.join("\n");
  expect(contentText).toContain("TESTINPUT");

  // ─── Check: selection works ────────────────────────────────
  await page.keyboard.press("Home");
  await page.keyboard.down("Shift");
  await page.keyboard.press("End");
  await page.keyboard.up("Shift");
  await page.waitForTimeout(300);

  const selectionInfo = await page.evaluate(() => {
    const sel = window.getSelection();
    const selLayer = document.querySelector(".cm-selectionLayer");
    const selBackground = document.querySelector(".cm-selectionBackground");
    return {
      selectionType: sel?.type,
      selectionLength: sel?.toString().length,
      hasSelectionLayer: !!selLayer,
      hasSelectionBackground: !!selBackground,
    };
  });
  console.log("\nSelection info:", JSON.stringify(selectionInfo, null, 2));

  await page.screenshot({ path: "e2e-cell-edit-diag.png", fullPage: true });

  if (errors.length > 0) {
    console.log("\nPage errors:", errors.slice(0, 10));
  }
});
