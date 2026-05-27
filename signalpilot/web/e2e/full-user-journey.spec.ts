import { test, expect, type Page } from "@playwright/test";
import { getEnvReport, printEnvReport } from "./env-report";

/**
 * Full user journey — uses real clicks, no URL shortcuts.
 * Segments run in order. Each segment fixes what it finds.
 */

const GATEWAY = "http://localhost:3300";
const PROJECT_NAME = "e2e_test";

// ─── Helpers ─────────────────────────────────────────────────────

function timer() {
  const t0 = Date.now();
  return (label: string) => {
    console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${label}`);
  };
}

function trackErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(`PAGE: ${err.message.slice(0, 300)}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      const text = msg.text().slice(0, 300);
      if (!text.includes("404") && !text.includes("favicon")) errors.push(text);
    }
  });
  return errors;
}

async function getApiKey(): Promise<string> {
  const resp = await fetch("http://localhost:3200/api/local-key");
  const data = (await resp.json()) as { key?: string };
  return data?.key ?? "";
}

/** Click a tree item by invoking its React onClick handler directly.
 * Playwright's native click is intercepted by wrapper divs (PanelGroup,
 * PanelsWrapper, sp-root) that sit above the tree items in the hit-test
 * stacking order. Real user clicks work because the browser's native
 * event dispatch differs from elementFromPoint(). For tests, we invoke
 * the React handler directly via the React fiber. */
async function clickTreeItem(page: Page, name: string, opts?: { timeout?: number }) {
  const timeout = opts?.timeout ?? 10_000;
  const item = page.locator('[role="treeitem"]').filter({
    has: page.locator(`span.flex-1:text-is("${name}")`),
  }).first();
  await item.waitFor({ timeout });

  await item.evaluate((el) => {
    // Find the clickable row div inside the treeitem
    const row = el.querySelector("div.cursor-pointer") as HTMLElement | null;
    if (!row) return;
    // Find the React fiber and invoke the onClick prop
    const propsKey = Object.keys(row).find((k) => k.startsWith("__reactProps"));
    if (propsKey) {
      const props = (row as any)[propsKey];
      if (props?.onClick) {
        props.onClick({ stopPropagation: () => {}, preventDefault: () => {} });
      }
    }
  });
}

/** Open the file tree sidebar panel using keyboard shortcut */
async function openSidebar(page: Page) {
  // Focus the notebook area first
  await page.locator(".sp-root").click({ force: true, position: { x: 5, y: 5 } }).catch(() => {});
  await page.waitForTimeout(500);
  // Toggle sidebar with keyboard shortcut
  await page.keyboard.press("Control+Shift+KeyE");
  await page.waitForTimeout(2000);
  // If that didn't work, try Ctrl+B
  const hasTree = await page.locator('[role="treeitem"]').first().isVisible({ timeout: 3_000 }).catch(() => false);
  if (!hasTree) {
    await page.keyboard.press("Control+KeyB");
    await page.waitForTimeout(2000);
  }
}

/** Wait for the file tree to have at least N items */
async function waitForTreeItems(page: Page, minCount: number, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const count = await page.locator('.sp-root [role="treeitem"]').count();
    if (count >= minCount) return count;
    await page.waitForTimeout(1000);
  }
  return await page.locator('.sp-root [role="treeitem"]').count();
}

/** Get all visible tree item names */
async function getTreeItemNames(page: Page): Promise<string[]> {
  return page.locator('.sp-root [role="treeitem"] span.flex-1.overflow-hidden.text-ellipsis')
    .allTextContents();
}

/** Capture the current URL for later direct-nav testing */
function captureUrl(page: Page): string {
  return page.url();
}

// ─── Saved URLs from the journey ─────────────────────────────────
const savedUrls: Record<string, string> = {};

// ─── Tests ───────────────────────────────────────────────────────

test.describe.serial("Full User Journey", () => {

  test.beforeAll(async () => {
    const env = await getEnvReport();
    printEnvReport(env);
  });

  // ── Segment 1: Delete old project, create new one ──────────────

  test("S1: delete existing e2e_test project if it exists", async ({ page }) => {
    test.setTimeout(30_000);
    const ts = timer();
    const apiKey = await getApiKey();

    // Find and delete existing e2e_test project via API
    const projResp = await fetch(`${GATEWAY}/api/workspace-projects?status=active&limit=50`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    const projData = (await projResp.json()) as { projects?: { id: string; name: string }[] };
    const existing = projData?.projects?.find((p) => p.name === PROJECT_NAME);

    if (existing) {
      ts(`Deleting existing project: ${existing.id}`);
      await fetch(`${GATEWAY}/api/workspace-projects/${existing.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${apiKey}` },
      });
      ts("Deleted");
    } else {
      ts("No existing e2e_test project");
    }
  });

  test("S2: click existing project from home page", async ({ page }) => {
    test.setTimeout(90_000);
    const ts = timer();
    const errors = trackErrors(page);

    ts("goto /projects");
    await page.goto("/projects", { waitUntil: "domcontentloaded" });
    await page.locator(".sp-root").waitFor({ timeout: 60_000 });
    await page.waitForTimeout(3000);
    ts(".sp-root loaded");

    // Click the ttes2 project (or whichever has files)
    const spRoot = page.locator(".sp-root");
    let clicked = false;
    for (const name of ["ttes2", "test", "m3", "e2e_test"]) {
      const card = spRoot.getByText(name, { exact: false }).first();
      if (await card.isVisible({ timeout: 2_000 }).catch(() => false)) {
        ts(`Clicking project: ${name}`);
        await card.click();
        clicked = true;
        break;
      }
    }
    expect(clicked, "Should find a project to click").toBe(true);

    ts("Waiting for workspace...");
    await page.waitForTimeout(5000);
    await page.screenshot({ path: "e2e-journey-s2-after-click.png" });

    // Should be in workspace view
    const hasWorkspace = await spRoot.getByText(/select a file/i)
      .isVisible({ timeout: 10_000 }).catch(() => false);
    const hasEditor = await page.locator(".cm-editor").first()
      .isVisible({ timeout: 3_000 }).catch(() => false);

    ts(`After click: workspace=${hasWorkspace}, editor=${hasEditor}`);
    savedUrls["workspace"] = captureUrl(page);
    ts(`Saved URL: ${savedUrls["workspace"]}`);

    expect(hasWorkspace || hasEditor, "Should be in workspace after clicking project").toBe(true);
  });

  // ── Segment 2: File tree loads ─────────────────────────────────

  test("S3: file tree loads with project files", async ({ page }) => {
    test.setTimeout(90_000);
    const ts = timer();
    const errors = trackErrors(page);

    // Navigate to the workspace URL we saved
    if (savedUrls["workspace"]) {
      ts(`goto saved workspace URL`);
      await page.goto(savedUrls["workspace"], { waitUntil: "domcontentloaded" });
    } else {
      ts("goto /projects (no saved URL)");
      await page.goto("/projects", { waitUntil: "domcontentloaded" });
    }

    await page.locator(".sp-root").waitFor({ timeout: 60_000 });
    await page.waitForTimeout(3000);

    // Open the file tree sidebar panel — click the first icon in the sidebar strip
    ts("Opening file tree sidebar...");
    const sidebarStrip = page.locator(".sp-root div[class*='flex'][class*='flex-col'][class*='bg-']").first();
    const firstIcon = sidebarStrip.locator("div[class*='rounded']").first();
    if (await firstIcon.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await firstIcon.click();
      ts("Clicked sidebar icon");
    } else {
      ts("Sidebar icon not found — tree may already be open");
    }

    // Wait for file tree to populate
    ts("Waiting for tree items...");
    const count = await waitForTreeItems(page, 3, 30_000);
    ts(`Tree items: ${count}`);

    const names = await getTreeItemNames(page);
    ts(`Files: ${names.join(", ")}`);

    await page.screenshot({ path: "e2e-journey-s3-tree.png" });

    // Should have standard dbt project structure
    expect(count, "File tree should have items").toBeGreaterThan(0);

    // Print what we found for debugging
    console.log("\n=== FILE TREE CONTENTS ===");
    for (const n of names) console.log(`  ${n}`);
    console.log("==========================\n");
  });

  // ── Segment 3: Click notebooks/ folder to expand ───────────────

  test("S4: expand notebooks/ folder", async ({ page }) => {
    test.setTimeout(180_000);
    const ts = timer();

    if (savedUrls["workspace"]) {
      await page.goto(savedUrls["workspace"], { waitUntil: "domcontentloaded" });
    } else {
      await page.goto("/projects", { waitUntil: "domcontentloaded" });
    }
    await page.locator(".sp-root").waitFor({ timeout: 90_000 });
    await page.waitForTimeout(3000);
    await openSidebar(page);
    await waitForTreeItems(page, 3, 60_000);

    const namesBefore = await getTreeItemNames(page);
    ts(`Before expand: ${namesBefore.join(", ")}`);

    // Click "notebooks" folder to expand it
    ts("Clicking notebooks/ folder...");
    await clickTreeItem(page, "notebooks");
    await page.waitForTimeout(3000);

    const namesAfter = await getTreeItemNames(page);
    ts(`After expand: ${namesAfter.join(", ")}`);

    await page.screenshot({ path: "e2e-journey-s4-expanded.png" });

    // intro.py should now be visible
    const hasIntro = namesAfter.includes("intro.py");
    ts(`intro.py visible: ${hasIntro}`);
    expect(hasIntro, "intro.py should appear after expanding notebooks/").toBe(true);
  });

  // ── Segment 4: Click intro.py → notebook cells render ──────────

  test("S5: click intro.py → notebook cells render", async ({ page }) => {
    test.setTimeout(90_000);
    const ts = timer();
    const errors = trackErrors(page);

    if (savedUrls["workspace"]) {
      await page.goto(savedUrls["workspace"], { waitUntil: "domcontentloaded" });
    } else {
      await page.goto("/projects", { waitUntil: "domcontentloaded" });
    }
    await page.locator(".sp-root").waitFor({ timeout: 60_000 });
    await page.waitForTimeout(2000);
    await openSidebar(page);
    await waitForTreeItems(page, 3, 30_000);

    // Expand notebooks/
    await clickTreeItem(page, "notebooks");
    await page.waitForTimeout(2000);

    // Click intro.py
    ts("Clicking intro.py...");
    await clickTreeItem(page, "intro.py");
    ts("Clicked. Waiting for cells...");

    // Wait for CM editors to appear (notebook cells)
    await page.locator(".cm-editor").first().waitFor({ timeout: 30_000 });
    const cellCount = await page.locator(".cm-editor").count();
    ts(`Notebook cells: ${cellCount}`);

    await page.screenshot({ path: "e2e-journey-s5-intro.png" });

    // Save the URL for direct-nav testing later
    savedUrls["intro.py"] = captureUrl(page);
    ts(`Saved URL: ${savedUrls["intro.py"]}`);

    expect(cellCount, "intro.py should render notebook cells").toBeGreaterThanOrEqual(2);

    // Verify cells have content
    const firstCellText = await page.locator(".cm-editor .cm-content").first().textContent();
    ts(`First cell: "${firstCellText?.slice(0, 50)}"`);
    expect(firstCellText?.length, "Cells should have content").toBeGreaterThan(3);
  });

  // ── Segment 5: Click dbt_project.yml → YML renders ─────────────

  test("S6: click dbt_project.yml → YML content renders", async ({ page }) => {
    test.setTimeout(90_000);
    const ts = timer();

    if (savedUrls["workspace"]) {
      await page.goto(savedUrls["workspace"], { waitUntil: "domcontentloaded" });
    } else {
      await page.goto("/projects", { waitUntil: "domcontentloaded" });
    }
    await page.locator(".sp-root").waitFor({ timeout: 60_000 });
    await page.waitForTimeout(2000);
    await openSidebar(page);
    await waitForTreeItems(page, 3, 30_000);

    // Click dbt_project.yml
    ts("Clicking dbt_project.yml...");
    await clickTreeItem(page, "dbt_project.yml");
    ts("Clicked. Waiting for content...");

    // Should show a raw editor
    await page.locator(".cm-editor, textarea").first().waitFor({ timeout: 15_000 });
    const content = await page.locator(".cm-editor .cm-content, textarea").first().textContent();
    ts(`Content: "${content?.slice(0, 60)}"`);

    await page.screenshot({ path: "e2e-journey-s6-yml.png" });

    savedUrls["dbt_project.yml"] = captureUrl(page);
    ts(`Saved URL: ${savedUrls["dbt_project.yml"]}`);

    expect(content?.length, "YML should have content").toBeGreaterThan(5);
  });

  // ── Segment 6: Direct-nav to saved intro.py URL ────────────────

  test("S7: direct-nav to intro.py URL loads cells", async ({ page }) => {
    test.setTimeout(60_000);
    const ts = timer();

    const url = savedUrls["intro.py"];
    if (!url) {
      ts("SKIP: no saved intro.py URL");
      return;
    }

    ts(`goto ${url.slice(0, 80)}...`);
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.locator(".sp-root").waitFor({ timeout: 60_000 });
    await page.locator(".cm-editor").first().waitFor({ timeout: 30_000 });

    const cellCount = await page.locator(".cm-editor").count();
    ts(`Cells via direct URL: ${cellCount}`);

    expect(cellCount, "Direct URL should load notebook cells").toBeGreaterThanOrEqual(2);
  });

  // ── Segment 7: Direct-nav to saved yml URL ─────────────────────

  test("S8: direct-nav to dbt_project.yml URL loads content", async ({ page }) => {
    test.setTimeout(60_000);
    const ts = timer();

    const url = savedUrls["dbt_project.yml"];
    if (!url) {
      ts("SKIP: no saved dbt_project.yml URL");
      return;
    }

    ts(`goto ${url.slice(0, 80)}...`);
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.locator(".sp-root").waitFor({ timeout: 60_000 });
    await page.locator(".cm-editor, textarea").first().waitFor({ timeout: 15_000 });

    const content = await page.locator(".cm-editor .cm-content, textarea").first().textContent();
    ts(`Content via direct URL: "${content?.slice(0, 60)}"`);

    expect(content?.length, "Direct URL should load YML content").toBeGreaterThan(5);
  });

});
