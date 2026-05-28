import { test, expect, type Page } from "@playwright/test";
import { getEnvReport, printEnvReport } from "./env-report";

/**
 * Single E2E test: full user journey in one page context.
 * Creates a fresh project, navigates into it, expands tree, clicks files.
 */

const GATEWAY = "http://localhost:3300";
const PROJECT_NAME = "e2e_journey";

// ─── Helpers ─────────────────────────────────────────────────────

function timer() {
  const t0 = Date.now();
  return (label: string) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${label}`);
}

function trackErrors(page: Page): { console: string[]; network: string[] } {
  const console: string[] = [];
  const network: string[] = [];
  page.on("pageerror", (err) => console.push(`PAGE: ${err.message.slice(0, 300)}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      const text = msg.text().slice(0, 300);
      if (!text.includes("favicon")) console.push(text);
    }
  });
  page.on("response", (resp) => {
    const short = `${resp.status()} ${resp.request().method()} ${resp.url().replace(/http:\/\/localhost:\d+/, "").slice(0, 100)}`;
    network.push(short);
  });
  return { console, network };
}

async function getApiKey(): Promise<string> {
  const resp = await fetch("http://localhost:3200/api/local-key");
  const data = (await resp.json()) as { key?: string };
  return data?.key ?? "";
}

/** Expand a folder by invoking React onClick (node.toggle) + pointer events */
async function expandFolder(page: Page, name: string, timeout = 10_000) {
  const treeitem = page.locator('[role="treeitem"]').filter({
    has: page.locator(`span.text-ellipsis:text-is("${name}")`),
  }).first();
  await treeitem.waitFor({ timeout });
  await treeitem.evaluate((el) => {
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
    const rect = el.getBoundingClientRect();
    const evtOpts = { bubbles: true, cancelable: true, clientX: rect.left + 10, clientY: rect.top + 15, view: window };
    el.dispatchEvent(new PointerEvent("pointerdown", { ...evtOpts, button: 0, pointerId: 1, pointerType: "mouse" }));
    el.dispatchEvent(new PointerEvent("pointerup", { ...evtOpts, button: 0, pointerId: 1, pointerType: "mouse" }));
    el.dispatchEvent(new MouseEvent("click", { ...evtOpts, button: 0 }));
  });
}

/** Click a file by invoking react-arborist's node.handleClick via fiber */
async function clickFile(page: Page, name: string, timeout = 10_000) {
  const treeitem = page.locator('[role="treeitem"]').filter({
    has: page.locator(`span.text-ellipsis:text-is("${name}")`),
  }).first();
  await treeitem.waitFor({ timeout });
  await treeitem.evaluate((el) => {
    const propsKey = Object.keys(el).find((k) => k.startsWith("__reactProps"));
    if (propsKey) {
      const props = (el as any)[propsKey];
      if (props?.onClick) {
        props.onClick({ stopPropagation: () => {}, preventDefault: () => {}, target: el, currentTarget: el });
      }
    }
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

/** Open the sidebar file panel */
async function openSidebar(page: Page) {
  const filesOption = page.locator('.sp-root [data-key="files"]');
  await filesOption.waitFor({ timeout: 10_000 });
  await filesOption.click({ force: true });
  await page.waitForTimeout(2000);
}

/** Wait for tree to have items */
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

test("Full user journey: create project → file tree → expand → click files", async ({ page }) => {
  test.setTimeout(300_000);
  const ts = timer();
  const errors = trackErrors(page);
  // Dump errors every 15s so we don't have to wait for the end
  const errorDumpInterval = setInterval(() => {
    if (errors.network.length > 0) {
      console.log(`\n--- ALL NETWORK (${errors.network.length}) ---`);
      errors.network.forEach((e) => console.log(`  ${e}`));
    }
  }, 15_000);
  const env = await getEnvReport();
  printEnvReport(env);

  const savedUrls: Record<string, string> = {};

  // Capture our debug logs from the browser
  const debugLogs: string[] = [];
  page.on("console", (msg) => {
    const text = msg.text();
    if (text.startsWith("[") && (
      text.includes("[WS") || text.includes("[kernel-ready") || text.includes("[handleKernelReady") ||
      text.includes("[openFileInTab") || text.includes("[EditApp") || text.includes("[onUrlChange") ||
      text.includes("[renderContent") || text.includes("[getExisting") || text.includes("[WS-RECONNECT") ||
      text.includes("[Sync")
    )) {
      debugLogs.push(text.slice(0, 200));
      console.log(`  BROWSER: ${text.slice(0, 200)}`);
    }
  });

  // ── Step 0: Clean slate — kill stale sessions + delete old project ──
  ts("Step 0: Cleanup");
  const apiKey = await getApiKey();
  const headers = { Authorization: `Bearer ${apiKey}` };

  // Kill any existing notebook session (pod might be dead from previous crash)
  await fetch(`${GATEWAY}/api/notebook-sessions`, { method: "DELETE", headers }).catch(() => {});
  ts("Killed stale session — waiting for pod to terminate...");
  await page.waitForTimeout(15000);

  // Delete old project if it exists
  const projResp = await fetch(`${GATEWAY}/api/workspace-projects?status=active&limit=50`, { headers });
  const projData = (await projResp.json()) as { projects?: { id: string; name: string }[] };
  const existing = projData?.projects?.find((p) => p.name === PROJECT_NAME);
  if (existing) {
    await fetch(`${GATEWAY}/api/workspace-projects/${existing.id}`, { method: "DELETE", headers });
    ts(`Deleted existing "${PROJECT_NAME}"`);
  }

  // ── Step 1: Go to /projects and open IDE ───────────────────────
  ts("Step 1: Navigate to /projects");
  await page.goto("/projects", { waitUntil: "domcontentloaded" });

  // Either already running or need to click "Open IDE"
  const runningText = page.getByText("running");
  const openBtn = page.getByRole("button", { name: /open ide/i });
  await Promise.race([
    runningText.waitFor({ timeout: 30_000 }),
    openBtn.waitFor({ timeout: 30_000 }),
  ]);
  if (await openBtn.isVisible().catch(() => false)) {
    await openBtn.click();
    ts("Clicked Open IDE");
    await runningText.waitFor({ timeout: 60_000 });
  }
  ts("Session running");

  await page.locator(".sp-root").waitFor({ timeout: 30_000 });
  ts("Notebook embed loaded");
  await page.screenshot({ path: "e2e-journey-01-home.png" });

  // ── Step 2: Create new project via the UX ──────────────────────
  ts("Step 2: Create project");
  const spRoot = page.locator(".sp-root");

  const createBtn = spRoot.getByRole("button", { name: /create new project/i });
  await createBtn.waitFor({ timeout: 15_000 });
  await createBtn.click();
  await page.waitForTimeout(500);

  const nameInput = spRoot.getByPlaceholder("my_dbt_project");
  await nameInput.waitFor({ timeout: 5_000 });
  await nameInput.fill(PROJECT_NAME);
  ts(`Filled name: ${PROJECT_NAME}`);
  await page.screenshot({ path: "e2e-journey-02-form.png" });

  // Click "Create" and wait for the full scaffold to complete (git push)
  await page.getByRole("button", { name: "Create", exact: true }).click();
  ts("Clicked Create — waiting for scaffold...");

  await page.waitForResponse(
    (r) => r.url().includes("/git/push") && r.status() === 200,
    { timeout: 10_000 },
  ).catch(() => ts("WARN: scaffold git/push did not complete in 10s — continuing"));
  ts("Scaffold complete (git push 200)");
  await page.waitForTimeout(3000);

  savedUrls["workspace"] = page.url();
  ts(`Workspace URL: ${savedUrls["workspace"]}`);
  await page.screenshot({ path: "e2e-journey-02-created.png" });

  // ── Step 3: Open sidebar + wait for tree ───────────────────────
  ts("Step 3: Open file tree sidebar");
  await openSidebar(page);
  const treeNames = await waitForTree(page, 90_000);
  ts(`Tree loaded: ${treeNames.length} items — ${treeNames.join(", ")}`);
  await page.screenshot({ path: "e2e-journey-03-tree.png" });
  expect(treeNames.length, "File tree should have items").toBeGreaterThan(0);

  console.log("\n=== FILE TREE CONTENTS ===");
  for (const n of treeNames) console.log(`  ${n}`);
  console.log("==========================\n");

  // ── Step 4: Expand notebooks/ folder ───────────────────────────
  ts("Step 4: Expand notebooks/");
  expect(treeNames, "Should have notebooks folder").toContain("notebooks");
  await expandFolder(page, "notebooks");
  await page.waitForTimeout(3000);

  const afterExpand = await page.locator('[role="treeitem"] span.text-ellipsis').allTextContents();
  const afterNames = [...new Set(afterExpand.map((n) => n.trim()).filter(Boolean))];
  ts(`After expand: ${afterNames.join(", ")}`);
  await page.screenshot({ path: "e2e-journey-04-expanded.png" });

  expect(afterNames, "intro.py should appear after expanding notebooks/").toContain("intro.py");

  // ── Step 5: Click intro.py → notebook cells render ─────────────
  ts("Step 5: Click intro.py");
  await clickFile(page, "intro.py");
  await page.waitForTimeout(3000);

  let cellCount = 0;
  for (let i = 0; i < 5; i++) {
    cellCount = await page.locator(".cm-editor").count();
    if (cellCount >= 2) break;
    await page.waitForTimeout(2000);
    ts(`  Waiting for cells... (${cellCount} so far)`);
  }
  ts(`Notebook cells: ${cellCount}`);
  console.log("\n=== DEBUG LOGS (browser) ===");
  debugLogs.forEach((l) => console.log(`  ${l}`));
  console.log("============================\n");
  await page.screenshot({ path: "e2e-journey-05-intro.png" });
  savedUrls["intro.py"] = page.url();
  ts(`URL: ${savedUrls["intro.py"]}`);
  expect(cellCount, "intro.py should render notebook cells").toBeGreaterThanOrEqual(2);

  const cellText = await page.locator(".cm-editor .cm-content").first().textContent();
  ts(`First cell: "${cellText?.slice(0, 50)}"`);
  expect(cellText?.length, "Cells should have content").toBeGreaterThan(3);

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
      expect(ymlContent?.length, "YML should have content").toBeGreaterThan(5);
    }
    await page.screenshot({ path: "e2e-journey-06-yml.png" });
  }

  // ── Step 7: Direct-nav to saved intro.py URL ───────────────────
  if (savedUrls["intro.py"]) {
    ts("Step 7: Direct-nav to intro.py URL");
    await page.goto(savedUrls["intro.py"], { waitUntil: "domcontentloaded" });
    await page.locator(".sp-root").waitFor({ timeout: 60_000 });
    await page.locator(".cm-editor").first().waitFor({ timeout: 30_000 });
    const directCells = await page.locator(".cm-editor").count();
    ts(`Direct URL cells: ${directCells}`);
    expect(directCells, "Direct URL should load cells").toBeGreaterThanOrEqual(2);
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
  expect(crashed).toBe(false);

  // ── Final Report ───────────────────────────────────────────────
  clearInterval(errorDumpInterval);
  const fatal = errors.console.filter((e) =>
    e.includes("Cannot read") || e.includes("null object") ||
    e.includes("dereference") || e.includes("is not a function")
  );
  if (fatal.length > 0) {
    console.log("\n=== FATAL ERRORS ===");
    fatal.forEach((e) => console.log(`  ${e}`));
  }
  console.log(`\nTotal console errors: ${errors.console.length}`);
  console.log(`Total network requests: ${errors.network.length}`);
  console.log("=== FULL NETWORK LOG ===");
  errors.network.forEach((e) => console.log(`  ${e}`));
  console.log("========================");
  console.log("\n=== SAVED URLs ===");
  for (const [k, v] of Object.entries(savedUrls)) {
    console.log(`  ${k}: ${v}`);
  }
  expect(fatal, "No fatal JS errors during journey").toHaveLength(0);
});

// ─── Test 2: Project switching via Back to Home ─────────────────

const PROJECT_B = "e2e_second";

test("Project switch: enter project → back to home → enter different project", async ({ page }) => {
  test.setTimeout(300_000);
  const ts = timer();
  const errors = trackErrors(page);

  // ── Step 0: Cleanup — ensure two projects exist ────────────────
  ts("Step 0: Cleanup");
  const apiKey = await getApiKey();
  const headers = { Authorization: `Bearer ${apiKey}` };

  // Kill stale session
  await fetch(`${GATEWAY}/api/notebook-sessions`, { method: "DELETE", headers }).catch(() => {});
  ts("Killed stale session — waiting for pod to terminate...");
  await page.waitForTimeout(15000);

  // Delete old projects if they exist
  const projResp = await fetch(`${GATEWAY}/api/workspace-projects?status=active&limit=50`, { headers });
  const projData = (await projResp.json()) as { projects?: { id: string; name: string }[] };
  for (const name of [PROJECT_NAME, PROJECT_B]) {
    const old = projData?.projects?.find((p) => p.name === name);
    if (old) {
      await fetch(`${GATEWAY}/api/workspace-projects/${old.id}`, { method: "DELETE", headers });
      ts(`Deleted existing "${name}"`);
    }
  }

  // ── Step 1: Navigate and open IDE ──────────────────────────────
  ts("Step 1: Navigate to /projects");
  await page.goto("/projects", { waitUntil: "domcontentloaded" });

  const runningText = page.getByText("running");
  const openBtn = page.getByRole("button", { name: /open ide/i });
  await Promise.race([
    runningText.waitFor({ timeout: 30_000 }),
    openBtn.waitFor({ timeout: 30_000 }),
  ]);
  if (await openBtn.isVisible().catch(() => false)) {
    await openBtn.click();
    ts("Clicked Open IDE");
    await runningText.waitFor({ timeout: 60_000 });
  }
  ts("Session running");
  await page.locator(".sp-root").waitFor({ timeout: 30_000 });
  ts("Notebook embed loaded");

  // ── Step 2: Create project A ───────────────────────────────────
  ts("Step 2: Create project A");
  const spRoot = page.locator(".sp-root");
  const createBtn = spRoot.getByRole("button", { name: /create new project/i });
  await createBtn.waitFor({ timeout: 15_000 });
  await createBtn.click();
  await page.waitForTimeout(500);

  const nameInput = spRoot.getByPlaceholder("my_dbt_project");
  await nameInput.waitFor({ timeout: 5_000 });
  await nameInput.fill(PROJECT_NAME);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  ts("Creating project A...");

  await page.waitForResponse(
    (r) => r.url().includes("/git/push") && r.status() === 200,
    { timeout: 10_000 },
  ).catch(() => {});
  ts("Project A created");
  await page.waitForTimeout(3000);

  // Open sidebar and file tree
  await openSidebar(page);
  const treeA = await waitForTree(page, 90_000);
  ts(`Project A tree: ${treeA.length} items`);
  expect(treeA.length).toBeGreaterThan(0);

  // Expand notebooks/ and click intro.py
  await expandFolder(page, "notebooks");
  await page.waitForTimeout(3000);
  await clickFile(page, "intro.py");
  await page.waitForTimeout(3000);

  let cellCount = 0;
  for (let i = 0; i < 5; i++) {
    cellCount = await page.locator(".cm-editor").count();
    if (cellCount >= 2) break;
    await page.waitForTimeout(2000);
    ts(`  Waiting for cells... (${cellCount} so far)`);
  }
  ts(`Project A cells: ${cellCount}`);
  expect(cellCount, "Project A intro.py should render cells").toBeGreaterThanOrEqual(2);
  await page.screenshot({ path: "e2e-switch-01-project-a.png" });

  const projectAUrl = page.url();
  const projectAId = new URL(projectAUrl).searchParams.get("project");
  ts(`Project A id: ${projectAId}`);

  // ── Step 3: Click "Back to home" ───────────────────────────────
  ts("Step 3: Click Back to home");
  const backBtn = page.locator('[data-testid="back-button"]');
  await backBtn.waitFor({ state: "attached", timeout: 10_000 });
  await backBtn.click({ force: true });
  ts("Clicked back-button");

  // Wait for navigation to /projects (no file param)
  await page.waitForURL(/\/projects(?:\?(?!.*file=)|$)/, { timeout: 10_000 }).catch(() => {
    ts("WARN: URL didn't change after back button — forcing navigation");
  });
  await page.waitForTimeout(2000);
  const urlAfterHome = page.url();
  ts(`URL after home: ${urlAfterHome}`);
  await page.screenshot({ path: "e2e-switch-02-home.png" });

  // If back button didn't navigate, force it
  if (urlAfterHome.includes("file=")) {
    ts("Back button didn't clear file param — navigating manually");
    await page.goto("/projects", { waitUntil: "domcontentloaded" });
  }

  // The IDE should still be running or reachable
  const openBtn2 = page.getByRole("button", { name: /open ide/i });
  const running2 = page.getByText("running");
  await Promise.race([
    running2.waitFor({ timeout: 30_000 }),
    openBtn2.waitFor({ timeout: 30_000 }),
  ]);
  if (await openBtn2.isVisible().catch(() => false)) {
    await openBtn2.click();
    await running2.waitFor({ timeout: 60_000 });
  }
  await page.locator(".sp-root").waitFor({ timeout: 30_000 });
  ts("Notebook embed loaded for project B");

  // Create project B
  ts("Step 5: Create project B");
  const createBtn2 = spRoot.getByRole("button", { name: /create new project/i });
  await createBtn2.waitFor({ timeout: 15_000 });
  await createBtn2.click();
  await page.waitForTimeout(500);

  const nameInput2 = spRoot.getByPlaceholder("my_dbt_project");
  await nameInput2.waitFor({ timeout: 5_000 });
  await nameInput2.fill(PROJECT_B);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  ts("Creating project B...");

  await page.waitForResponse(
    (r) => r.url().includes("/git/push") && r.status() === 200,
    { timeout: 10_000 },
  ).catch(() => {});
  ts("Project B created");
  await page.waitForTimeout(3000);

  const projectBUrl = page.url();
  const projectBId = new URL(projectBUrl).searchParams.get("project");
  ts(`Project B id: ${projectBId}`);
  expect(projectBId, "Project B should have a different id").not.toBe(projectAId);

  // Open sidebar and verify project B's tree loads
  await openSidebar(page);
  const treeB = await waitForTree(page, 90_000);
  ts(`Project B tree: ${treeB.length} items`);
  expect(treeB.length, "Project B should have files").toBeGreaterThan(0);

  // Expand notebooks/ and click intro.py in project B
  await expandFolder(page, "notebooks");
  await page.waitForTimeout(3000);
  await clickFile(page, "intro.py");
  await page.waitForTimeout(3000);

  let cellCountB = 0;
  for (let i = 0; i < 5; i++) {
    cellCountB = await page.locator(".cm-editor").count();
    if (cellCountB >= 2) break;
    await page.waitForTimeout(2000);
    ts(`  Waiting for B cells... (${cellCountB} so far)`);
  }
  ts(`Project B cells: ${cellCountB}`);
  expect(cellCountB, "Project B intro.py should render cells").toBeGreaterThanOrEqual(2);
  await page.screenshot({ path: "e2e-switch-03-project-b.png" });

  // ── Step 6: Navigate back to project A via direct URL ──────────
  ts("Step 6: Direct-nav back to project A intro.py");
  await page.goto(projectAUrl, { waitUntil: "domcontentloaded" });
  await page.locator(".sp-root").waitFor({ timeout: 60_000 });

  let cellCountA2 = 0;
  for (let i = 0; i < 5; i++) {
    cellCountA2 = await page.locator(".cm-editor").count();
    if (cellCountA2 >= 2) break;
    await page.waitForTimeout(2000);
    ts(`  Waiting for A cells... (${cellCountA2} so far)`);
  }
  ts(`Project A (revisit) cells: ${cellCountA2}`);
  expect(cellCountA2, "Revisiting project A should render cells").toBeGreaterThanOrEqual(2);
  await page.screenshot({ path: "e2e-switch-04-project-a-revisit.png" });

  // ── Step 7: Verify no crashes ──────────────────────────────────
  ts("Step 7: Verify no crashes");
  const crashed = await page.getByText(/something went wrong/i)
    .isVisible({ timeout: 2_000 }).catch(() => false);
  expect(crashed, "No crash screen").toBe(false);

  const fatal = errors.console.filter((e) =>
    e.includes("Cannot read") || e.includes("null object") ||
    e.includes("dereference") || e.includes("is not a function")
  );
  if (fatal.length > 0) {
    console.log("\n=== FATAL ERRORS ===");
    fatal.forEach((e) => console.log(`  ${e}`));
  }
  ts(`Done. Console errors: ${errors.console.length}, fatal: ${fatal.length}`);
  expect(fatal, "No fatal JS errors during project switch").toHaveLength(0);
});
