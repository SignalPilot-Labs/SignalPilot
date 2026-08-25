import { test, expect, type Page } from "@playwright/test";

import { resolveProject } from "./helpers";

/**
 * File-tree interaction regression suite.
 *
 * Guards the failure mode where the tree loads once and then clicking any
 * node wipes/hides entries. Every interaction must leave the tree populated
 * and produce zero fatal console errors.
 */

let PROJECT_ID = "";

test.beforeAll(async ({ request }) => {
  PROJECT_ID = (await resolveProject(request)).id;
});

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(`PAGE: ${err.message.slice(0, 300)}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`CONSOLE: ${msg.text().slice(0, 300)}`);
  });
  return errors;
}

async function openTree(page: Page) {
  await page.goto(
    `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
    { waitUntil: "domcontentloaded" },
  );
  await page.locator(".sp-root").waitFor({ timeout: 90_000 });
  await page.locator(".cm-editor").first().waitFor({ timeout: 60_000 });
  const toggle = page.getByLabel("View files").first();
  await toggle.waitFor({ timeout: 15_000 });
  await toggle.click();
  await page.locator("[role=treeitem]").first().waitFor({ timeout: 20_000 });
}

async function treeCount(page: Page): Promise<number> {
  return page.locator("[role=treeitem]").count();
}

test("tree survives folder expansion, file clicks, and refresh cycles", async ({ page }) => {
  test.setTimeout(180_000);
  const errors = collectErrors(page);
  await openTree(page);

  const initial = await treeCount(page);
  expect(initial, "tree should show entries after opening").toBeGreaterThan(0);

  for (let cycle = 1; cycle <= 3; cycle++) {
    // Expand a folder
    const folder = page.locator("[role=treeitem]").filter({ hasText: /^notebooks$/ }).first();
    if (await folder.count()) {
      await folder.click();
      await page.waitForTimeout(1000);
      const afterExpand = await treeCount(page);
      expect(afterExpand, `cycle ${cycle}: tree emptied after folder click`).toBeGreaterThan(0);
    }

    // Click a file inside it
    const file = page.locator("[role=treeitem]").filter({ hasText: "intro.py" }).first();
    if (await file.count()) {
      await file.click();
      await page.waitForTimeout(1500);
      expect(await treeCount(page), `cycle ${cycle}: tree emptied after file click`).toBeGreaterThan(0);
      // The editor should still show the notebook
      expect(await page.locator(".cm-editor").count()).toBeGreaterThan(0);
    }

    // Refresh the tree via its toolbar
    const refresh = page.locator("[data-testid=file-explorer-refresh-button]").first();
    if (await refresh.count()) {
      await refresh.click();
      await page.waitForTimeout(1500);
      expect(await treeCount(page), `cycle ${cycle}: tree emptied after refresh`).toBeGreaterThan(0);
    }
  }

  const fatal = errors.filter(
    (e) => e.includes("TypeError") || e.includes("404") || e.includes("500"),
  );
  expect(fatal, `fatal/HTTP errors during tree use: ${fatal.slice(0, 5).join(" | ")}`).toHaveLength(0);
});

test("switching between file types keeps tree and editor consistent", async ({ page }) => {
  test.setTimeout(180_000);
  const errors = collectErrors(page);
  await openTree(page);

  // Walk into dumpsters_dbt and open a few different file types from the tree.
  const dbtFolder = page.locator("[role=treeitem]").filter({ hasText: /^dumpsters_dbt$/ }).first();
  if (await dbtFolder.count()) {
    await dbtFolder.click();
    await page.waitForTimeout(1500);
  }
  expect(await treeCount(page)).toBeGreaterThan(0);

  // Whatever entries exist now, click through the first few and ensure
  // the tree never collapses to zero.
  const entries = page.locator("[role=treeitem]");
  const n = Math.min(await entries.count(), 5);
  for (let i = 0; i < n; i++) {
    await entries.nth(i).click();
    await page.waitForTimeout(800);
    expect(await treeCount(page), `tree emptied after clicking entry ${i}`).toBeGreaterThan(0);
  }

  const fatal = errors.filter((e) => e.includes("TypeError"));
  expect(fatal, fatal.join(" | ")).toHaveLength(0);
});

test("tree state survives a page reload", async ({ page }) => {
  test.setTimeout(120_000);
  await openTree(page);
  const before = await treeCount(page);
  expect(before).toBeGreaterThan(0);

  await page.reload({ waitUntil: "domcontentloaded" });
  await page.locator(".sp-root").waitFor({ timeout: 90_000 });
  await page.locator(".cm-editor").first().waitFor({ timeout: 60_000 });
  // Panel state persists (localStorage); if closed, open it again.
  if ((await page.locator("[role=treeitem]").count()) === 0) {
    const toggle = page.getByLabel("View files").first();
    if (await toggle.count()) await toggle.click();
  }
  await page.locator("[role=treeitem]").first().waitFor({ timeout: 20_000 });
  expect(await treeCount(page)).toBeGreaterThan(0);
});
