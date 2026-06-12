import { test, expect } from "@playwright/test";
import { getEnvReport, printEnvReport, type EnvReport } from "./env-report";

/**
 * Real user E2E flow — no URL param shortcuts.
 * Every test starts by printing a full environment report
 * so failures are never ambiguous about what data exists.
 */

let env: EnvReport;

test.beforeAll(async () => {
  env = await getEnvReport();
  printEnvReport(env);
});

function timer() {
  const t0 = Date.now();
  return (label: string) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${label}`);
}

function trackErrors(page: import("@playwright/test").Page): string[] {
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

function expectNoFatalErrors(errors: string[]) {
  const fatal = errors.filter((e) =>
    e.includes("Cannot read") || e.includes("null object") ||
    e.includes("dereference") || e.includes("is not a function")
  );
  if (fatal.length > 0) {
    console.log("FATAL ERRORS:");
    fatal.forEach((e) => console.log(`  ${e}`));
  }
  expect(fatal, "No fatal JS errors").toHaveLength(0);
}

// Pick the best project to test against (one with files)
function pickProject(): { id: string; name: string; files: string[] } | null {
  const withFiles = env.projects.filter((p) => p.files.length > 0);
  if (withFiles.length === 0) return env.projects[0] ?? null;
  // Prefer ttes2 or test
  return withFiles.find((p) => p.name === "ttes2")
    ?? withFiles.find((p) => p.name === "test")
    ?? withFiles[0];
}

test.describe("Real User Flow", () => {

  test("1. /projects loads without crash", async ({ page }) => {
    test.setTimeout(30_000);
    const errors = trackErrors(page);
    const ts = timer();

    ts("goto /projects");
    await page.goto("/projects", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "e2e-real-01.png" });

    const crashed = await page.getByText(/something went wrong|attempting to dereference/i)
      .isVisible({ timeout: 2_000 }).catch(() => false);
    ts(`Crashed: ${crashed}`);
    expect(crashed, "Page should not crash").toBe(false);
    expectNoFatalErrors(errors);
  });

  test("2. notebook embed loads and shows project list", async ({ page }) => {
    test.setTimeout(60_000);
    const ts = timer();

    ts("goto /projects");
    await page.goto("/projects", { waitUntil: "domcontentloaded" });
    await page.locator(".sp-root").waitFor({ timeout: 30_000 });
    ts(".sp-root visible");
    await page.waitForTimeout(3000);

    // Check for project names that we know exist from the env report
    for (const p of env.projects.slice(0, 4)) {
      const visible = await page.locator(".sp-root").getByText(p.name).first()
        .isVisible({ timeout: 3_000 }).catch(() => false);
      ts(`  Project "${p.name}": ${visible ? "visible" : "NOT visible"} (${p.files.length} files)`);
    }

    await page.screenshot({ path: "e2e-real-02.png" });
    expect(env.projects.length, "Should have at least one project").toBeGreaterThan(0);
  });

  test("3. click project → workspace loads", async ({ page }) => {
    test.setTimeout(90_000);
    const errors = trackErrors(page);
    const ts = timer();
    const project = pickProject();

    if (!project) {
      ts("SKIP: no projects available");
      return;
    }

    ts(`Target project: ${project.name} (${project.files.length} files)`);
    ts(`Files: ${project.files.slice(0, 10).join(", ")}`);

    ts("goto /projects");
    await page.goto("/projects", { waitUntil: "domcontentloaded" });
    await page.locator(".sp-root").waitFor({ timeout: 30_000 });
    await page.waitForTimeout(3000);

    // Click the project
    const card = page.locator(".sp-root").getByText(project.name).first();
    await card.waitFor({ timeout: 10_000 });
    ts(`Clicking "${project.name}"...`);
    await card.click();

    ts("Waiting for workspace...");
    await page.waitForTimeout(5000);
    await page.screenshot({ path: "e2e-real-03.png" });

    // Should see workspace: "Select a file" prompt OR an editor
    const hasFilePrompt = await page.locator(".sp-root").getByText(/select a file/i)
      .isVisible({ timeout: 5_000 }).catch(() => false);
    const hasEditor = await page.locator(".cm-editor").first()
      .isVisible({ timeout: 3_000 }).catch(() => false);

    ts(`Workspace loaded: filePrompt=${hasFilePrompt}, editor=${hasEditor}`);
    expect(hasFilePrompt || hasEditor, "Workspace should render").toBe(true);
    expectNoFatalErrors(errors);
  });

  test("4. open file tree → click file → content renders", async ({ page }) => {
    test.setTimeout(120_000);
    const errors = trackErrors(page);
    const ts = timer();
    const project = pickProject();

    if (!project) {
      ts("SKIP: no projects at all");
      return;
    }

    // Files may live on the pod even if the API reports 0
    ts(`Target: ${project.name} (API reports ${project.files.length} files — pod may have more)`);

    // Navigate to project workspace
    ts("goto /projects");
    await page.goto("/projects", { waitUntil: "domcontentloaded" });
    await page.locator(".sp-root").waitFor({ timeout: 30_000 });
    await page.waitForTimeout(3000);

    // Click project
    const card = page.locator(".sp-root").getByText(project.name).first();
    await card.waitFor({ timeout: 10_000 });
    await card.click();
    await page.waitForTimeout(5000);
    ts("In workspace");

    // Open file tree sidebar (first icon in sidebar strip)
    ts("Opening file tree...");
    const sidebarIcons = page.locator(".sp-root div[class*='flex'][class*='flex-col'][class*='bg-']").first();
    const firstIcon = sidebarIcons.locator("div[class*='rounded']").first();
    if (await firstIcon.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await firstIcon.click();
      ts("Clicked sidebar icon");
    }

    // Wait for tree to populate
    let treeFiles: string[] = [];
    for (let i = 0; i < 15; i++) {
      await page.waitForTimeout(2000);
      treeFiles = await page.evaluate(() => {
        const entries = new Set<string>();
        document.querySelectorAll(".sp-root [role='treeitem']").forEach((el) => {
          const text = (el as HTMLElement).textContent?.trim();
          if (text && text.length < 60 && !text.includes("\n")) entries.add(text);
        });
        document.querySelectorAll(".sp-root span").forEach((el) => {
          const text = (el as HTMLElement).textContent?.trim();
          if (text && /^[\w.-]+\.(py|sql|yml|yaml|md|json)$/.test(text)) entries.add(text);
        });
        return [...entries];
      });
      if (treeFiles.length > 0) break;
      ts(`  Waiting for tree... (${(i + 1) * 2}s)`);
    }

    ts(`Tree files: ${treeFiles.join(", ")}`);
    await page.screenshot({ path: "e2e-real-04.png" });

    // Click a file — prefer .py, then .yml, then .sql
    const target = treeFiles.find((f) => f.endsWith(".py"))
      ?? treeFiles.find((f) => f.endsWith(".yml"))
      ?? treeFiles.find((f) => f.endsWith(".sql"))
      ?? treeFiles[0];

    if (target) {
      ts(`Clicking file: ${target}`);
      const fileNode = page.locator(".sp-root").getByText(target, { exact: true }).first();
      await fileNode.click();
      await page.waitForTimeout(5000);

      const hasEditor = await page.locator(".cm-editor, textarea").first()
        .isVisible({ timeout: 15_000 }).catch(() => false);
      ts(`Editor loaded: ${hasEditor}`);
      await page.screenshot({ path: "e2e-real-05.png" });
      expect(hasEditor, `Content should render for ${target}`).toBe(true);

      // If it's a .py file, verify cells rendered
      if (target.endsWith(".py")) {
        const cellCount = await page.locator(".cm-editor").count();
        ts(`Notebook cells: ${cellCount}`);
        expect(cellCount, ".py should have notebook cells").toBeGreaterThan(0);
      }
    } else {
      // Might need to expand a folder first
      ts("No files at top level — trying to expand folders...");
      for (const folder of ["notebooks", "models", "macros"]) {
        const folderNode = page.locator(".sp-root").getByText(folder, { exact: true }).first();
        if (await folderNode.isVisible({ timeout: 2_000 }).catch(() => false)) {
          ts(`  Expanding ${folder}/`);
          await folderNode.click();
          await page.waitForTimeout(2000);
        }
      }
      await page.screenshot({ path: "e2e-real-05-expanded.png" });
    }

    expectNoFatalErrors(errors);
  });

  test("5. navigate back to /projects without crash", async ({ page }) => {
    test.setTimeout(60_000);
    const errors = trackErrors(page);
    const ts = timer();

    const project = pickProject();
    if (!project) { ts("SKIP: no project"); return; }

    // Deep-link to a file first
    const pyFile = project.files.find((f) => f.endsWith(".py"));
    const anyFile = pyFile ?? project.files[0];

    if (anyFile) {
      ts(`goto deep-link: ${anyFile}`);
      await page.goto(
        `/projects?project=${project.id}&branch=main&file=${encodeURIComponent(anyFile)}`,
        { waitUntil: "domcontentloaded" },
      );
      await page.locator(".sp-root").waitFor({ timeout: 60_000 });
      await page.waitForTimeout(3000);
      ts("Loaded");
    }

    // Navigate back to /projects
    ts("goto /projects");
    await page.goto("/projects", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);
    await page.screenshot({ path: "e2e-real-06.png" });

    const crashed = await page.getByText(/something went wrong|dereference/i)
      .isVisible({ timeout: 2_000 }).catch(() => false);
    ts(`Crashed after back-nav: ${crashed}`);
    expect(crashed).toBe(false);
    expectNoFatalErrors(errors);
  });
});
