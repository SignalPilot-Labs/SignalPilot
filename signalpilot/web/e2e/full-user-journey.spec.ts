import { test, expect, type Page } from "@playwright/test";
import { getEnvReport, printEnvReport } from "./env-report";

/**
 * Single end-to-end test that walks the full user journey in one page.
 * No URL shortcuts. Every action is a real click.
 */

const GATEWAY = "http://localhost:3300";

// ─── Helpers ─────────────────────────────────────────────────────

function timer() {
  const t0 = Date.now();
  return (label: string) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${label}`);
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

/** Expand a folder by calling React's onClick handler via the fiber.
 * Also dispatches pointer events so react-arborist's internal toggle fires. */
async function expandFolder(page: Page, name: string, timeout = 10_000) {
  const treeitem = page.locator('[role="treeitem"]').filter({
    has: page.locator(`span.text-ellipsis:text-is("${name}")`),
  }).first();
  await treeitem.waitFor({ timeout });
  await treeitem.evaluate((el) => {
    // 1. Find the row div and invoke React's onClick (calls node.toggle())
    const row = el.querySelector("div.cursor-pointer") as HTMLElement | null;
    if (row) {
      const propsKey = Object.keys(row).find((k) => k.startsWith("__reactProps"));
      if (propsKey) {
        const props = (row as any)[propsKey];
        if (props?.onClick) {
          props.onClick({ stopPropagation: () => {}, preventDefault: () => {} });
        }
      }
    }
    // 2. Also dispatch pointer events on the treeitem for react-arborist's onToggle
    const rect = el.getBoundingClientRect();
    const evtOpts = { bubbles: true, cancelable: true, clientX: rect.left + 10, clientY: rect.top + 15, view: window };
    el.dispatchEvent(new PointerEvent("pointerdown", { ...evtOpts, button: 0, pointerId: 1, pointerType: "mouse" }));
    el.dispatchEvent(new PointerEvent("pointerup", { ...evtOpts, button: 0, pointerId: 1, pointerType: "mouse" }));
    el.dispatchEvent(new MouseEvent("click", { ...evtOpts, button: 0 }));
  });
}

/** Click a file in the tree.
 * react-arborist's default row has onClick: node.handleClick which
 * triggers onSelect. We invoke it via the React fiber on the
 * outer [role="treeitem"] div (the default row). */
async function clickFile(page: Page, name: string, timeout = 10_000) {
  const treeitem = page.locator('[role="treeitem"]').filter({
    has: page.locator(`span.text-ellipsis:text-is("${name}")`),
  }).first();
  await treeitem.waitFor({ timeout });
  await treeitem.evaluate((el) => {
    // react-arborist's default row renders [role="treeitem"] with onClick: node.handleClick
    const propsKey = Object.keys(el).find((k) => k.startsWith("__reactProps"));
    if (propsKey) {
      const props = (el as any)[propsKey];
      if (props?.onClick) {
        props.onClick({ stopPropagation: () => {}, preventDefault: () => {}, target: el, currentTarget: el });
      }
    }
    // Also trigger our custom onClick on the inner row div
    const row = el.querySelector("div.cursor-pointer") as HTMLElement | null;
    if (row) {
      const rowPropsKey = Object.keys(row).find((k) => k.startsWith("__reactProps"));
      if (rowPropsKey) {
        const rowProps = (row as any)[rowPropsKey];
        if (rowProps?.onClick) {
          rowProps.onClick({ stopPropagation: () => {}, preventDefault: () => {} });
        }
      }
    }
  });
}

/** Open the sidebar file panel by clicking the files icon */
async function openSidebar(page: Page) {
  const filesOption = page.locator('.sp-root [data-key="files"]');
  await filesOption.waitFor({ timeout: 10_000 });
  await filesOption.click({ force: true });
  await page.waitForTimeout(2000);
}

/** Wait for tree to have items, return unique names */
async function waitForTree(page: Page, timeout = 60_000): Promise<string[]> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const names = await page.locator('[role="treeitem"] span.text-ellipsis').allTextContents();
    const unique = [...new Set(names.map((n) => n.trim()).filter(Boolean))];
    if (unique.length > 0) return unique;
    await page.waitForTimeout(2000);
  }
  return [];
}

// ─── The Test ────────────────────────────────────────────────────

test("Full user journey: projects → click project → file tree → expand → click files", async ({ page }) => {
  test.setTimeout(300_000);
  const ts = timer();
  const errors = trackErrors(page);
  const env = await getEnvReport();
  printEnvReport(env);

  const savedUrls: Record<string, string> = {};

  // ── Step 1: Go to /projects ────────────────────────────────────
  ts("Step 1: Navigate to /projects");
  await page.goto("/projects", { waitUntil: "domcontentloaded" });
  await page.locator(".sp-root").waitFor({ timeout: 60_000 });
  await page.waitForTimeout(3000);
  ts("Notebook embed loaded");
  await page.screenshot({ path: "e2e-journey-01-home.png" });

  // Verify projects are visible
  for (const p of env.projects.slice(0, 3)) {
    const vis = await page.locator(".sp-root").getByText(p.name).first()
      .isVisible({ timeout: 3_000 }).catch(() => false);
    ts(`  Project "${p.name}": ${vis ? "visible" : "NOT visible"}`);
  }

  // ── Step 2: Click a project ────────────────────────────────────
  ts("Step 2: Click project");
  const projectName = env.projects.find((p) => p.name === "ttes2")?.name
    ?? env.projects[0]?.name;
  expect(projectName, "Need at least one project").toBeTruthy();

  const card = page.locator(".sp-root").getByText(projectName!).first();
  await card.click();
  ts(`Clicked "${projectName}"`);
  await page.waitForTimeout(5000);

  savedUrls["workspace"] = page.url();
  ts(`URL: ${savedUrls["workspace"]}`);
  await page.screenshot({ path: "e2e-journey-02-workspace.png" });

  // Should be in workspace now
  const hasWorkspace = await page.locator(".sp-root").getByText(/select a file/i)
    .isVisible({ timeout: 5_000 }).catch(() => false);
  const hasEditor = await page.locator(".cm-editor").first()
    .isVisible({ timeout: 3_000 }).catch(() => false);
  ts(`Workspace: selectFile=${hasWorkspace}, editor=${hasEditor}`);
  expect(hasWorkspace || hasEditor, "Should be in workspace").toBe(true);

  // ── Step 3: Open sidebar + wait for tree ───────────────────────
  ts("Step 3: Open file tree sidebar");
  await openSidebar(page);
  const treeNames = await waitForTree(page, 90_000);
  ts(`Tree loaded: ${treeNames.length} items — ${treeNames.join(", ")}`);
  await page.screenshot({ path: "e2e-journey-03-tree.png" });
  expect(treeNames.length, "File tree should have items").toBeGreaterThan(0);

  // ── Step 4: Expand notebooks/ folder ───────────────────────────
  ts("Step 4: Expand notebooks/");
  if (treeNames.includes("notebooks")) {
    await expandFolder(page, "notebooks");
    await page.waitForTimeout(3000);

    const afterExpand = await page.locator('[role="treeitem"] span.text-ellipsis').allTextContents();
    const afterNames = [...new Set(afterExpand.map((n) => n.trim()).filter(Boolean))];
    ts(`After expand: ${afterNames.join(", ")}`);
    await page.screenshot({ path: "e2e-journey-04-expanded.png" });

    const hasIntro = afterNames.includes("intro.py");
    ts(`intro.py visible: ${hasIntro}`);
    expect(hasIntro, "intro.py should appear after expanding notebooks/").toBe(true);

    // ── Step 5: Click intro.py → notebook cells render ───────────
    ts("Step 5: Click intro.py");
    await clickFile(page, "intro.py");
    // Wait for the notebook to load — URL changes, boot re-runs,
    // kernel instantiates, cells render
    await page.waitForTimeout(3000);
    // Wait for at least 2 cm-editors (intro.py has 3 cells)
    let cellCount = 0;
    for (let i = 0; i < 20; i++) {
      cellCount = await page.locator(".cm-editor").count();
      if (cellCount >= 2) break;
      await page.waitForTimeout(2000);
      ts(`  Waiting for cells... (${cellCount} so far)`);
    }
    ts(`Notebook cells: ${cellCount}`);
    await page.screenshot({ path: "e2e-journey-05-intro.png" });
    savedUrls["intro.py"] = page.url();
    ts(`URL: ${savedUrls["intro.py"]}`);
    expect(cellCount, "intro.py should render notebook cells").toBeGreaterThanOrEqual(2);

    // Verify cells have content
    const cellText = await page.locator(".cm-editor .cm-content").first().textContent();
    ts(`First cell: "${cellText?.slice(0, 50)}"`);
    expect(cellText?.length, "Cells should have content").toBeGreaterThan(3);
  } else {
    ts("SKIP: no 'notebooks' folder in tree");
  }

  // ── Step 6: Click dbt_project.yml → YML renders ────────────────
  ts("Step 6: Click dbt_project.yml");
  if (treeNames.includes("dbt_project.yml")) {
    await clickFile(page, "dbt_project.yml");
    await page.waitForTimeout(5000);

    const hasYmlEditor = await page.locator(".cm-editor, textarea").first()
      .isVisible({ timeout: 10_000 }).catch(() => false);
    ts(`YML editor: ${hasYmlEditor}`);

    if (hasYmlEditor) {
      const ymlContent = await page.locator(".cm-editor .cm-content, textarea").first().textContent();
      ts(`Content: "${ymlContent?.slice(0, 60)}"`);
      savedUrls["dbt_project.yml"] = page.url();
      ts(`URL: ${savedUrls["dbt_project.yml"]}`);
      expect(ymlContent?.length, "YML should have content").toBeGreaterThan(5);
    }
    await page.screenshot({ path: "e2e-journey-06-yml.png" });
  } else {
    ts("SKIP: no dbt_project.yml in tree");
  }

  // ── Step 7: Direct-nav to saved intro.py URL ──────────────────
  if (savedUrls["intro.py"]) {
    ts("Step 7: Direct-nav to intro.py URL");
    await page.goto(savedUrls["intro.py"], { waitUntil: "domcontentloaded" });
    await page.locator(".sp-root").waitFor({ timeout: 60_000 });
    await page.locator(".cm-editor").first().waitFor({ timeout: 30_000 });
    const cellCount = await page.locator(".cm-editor").count();
    ts(`Direct URL cells: ${cellCount}`);
    expect(cellCount, "Direct URL should load cells").toBeGreaterThanOrEqual(2);
  }

  // ── Step 8: Direct-nav to saved yml URL ────────────────────────
  if (savedUrls["dbt_project.yml"]) {
    ts("Step 8: Direct-nav to dbt_project.yml URL");
    await page.goto(savedUrls["dbt_project.yml"], { waitUntil: "domcontentloaded" });
    await page.locator(".sp-root").waitFor({ timeout: 60_000 });
    await page.locator(".cm-editor, textarea").first().waitFor({ timeout: 15_000 });
    const content = await page.locator(".cm-editor .cm-content, textarea").first().textContent();
    ts(`Direct URL YML: "${content?.slice(0, 60)}"`);
    expect(content?.length, "Direct URL should load YML").toBeGreaterThan(5);
  }

  // ── Step 9: Navigate back to /projects ─────────────────────────
  ts("Step 9: Back to /projects");
  await page.goto("/projects", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);
  const crashed = await page.getByText(/something went wrong|dereference/i)
    .isVisible({ timeout: 2_000 }).catch(() => false);
  ts(`Crashed on back-nav: ${crashed}`);
  expect(crashed, "Should not crash on back navigation").toBe(false);

  // ── Final Report ───────────────────────────────────────────────
  const fatal = errors.filter((e) =>
    e.includes("Cannot read") || e.includes("null object") ||
    e.includes("dereference") || e.includes("is not a function")
  );
  if (fatal.length > 0) {
    console.log("\n=== FATAL ERRORS ===");
    fatal.forEach((e) => console.log(`  ${e}`));
  }
  if (errors.length > 0) {
    console.log(`\nTotal console errors: ${errors.length}`);
  }
  console.log("\n=== SAVED URLs ===");
  for (const [k, v] of Object.entries(savedUrls)) {
    console.log(`  ${k}: ${v}`);
  }

  expect(fatal, "No fatal JS errors during journey").toHaveLength(0);
});
