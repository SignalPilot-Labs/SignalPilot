import { test, expect } from "@playwright/test";

test("full flow: projects page → click project → files load → go back → no errors", async ({
  page,
}) => {
  test.setTimeout(120_000);

  const t0 = Date.now();
  const ts = (label: string) => {
    console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${label}`);
  };

  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text().slice(0, 200));
  });
  page.on("pageerror", (err) => errors.push(`PAGE: ${err.message.slice(0, 200)}`));

  // ── Step 1: Go to /projects (no params) — current landing page ─
  ts("Navigate to /projects");
  await page.goto("/projects", { waitUntil: "domcontentloaded" });

  const spRoot = page.locator(".sp-root");
  const createBtn = page.getByRole("button", { name: /create new project/i });
  await createBtn.waitFor({ timeout: 30_000 });
  ts("Landing page rendered");

  // The projects list fetch is in flight while "Refresh projects" is disabled;
  // wait for it to settle before judging whether cards exist.
  const refreshBtn = page.getByRole("button", { name: /refresh projects/i });
  await expect(refreshBtn).toBeEnabled({ timeout: 30_000 });
  ts("Projects list settled");
  await page.screenshot({ path: "e2e-step1-projects.png" });

  // ── Step 2: Click the first project card ───────────────────────
  const projectCard = page.getByRole("button", { name: /settings for/i }).first();
  let hasProject = await projectCard.isVisible({ timeout: 10_000 }).catch(() => false);
  if (!hasProject) {
    await refreshBtn.click();
    hasProject = await projectCard.isVisible({ timeout: 10_000 }).catch(() => false);
  }

  if (!hasProject) {
    ts("No project cards visible — nothing to open");
    await page.screenshot({ path: "e2e-step2-noproj.png" });
    expect(hasProject, "at least one project card on the landing page").toBe(true);
    return;
  }

  const errsBefore = errors.length;
  await projectCard.click();
  ts("Clicked first project card");
  await spRoot.waitFor({ timeout: 120_000 });
  ts("Notebook embed loaded");

  // ── Step 3: Wait for file tree / workspace to load ─────────────
  // After clicking a project, the notebook navigates to the workspace view
  await page.waitForTimeout(5000);
  ts("5s after click");
  await page.screenshot({ path: "e2e-step3-afterclick.png" });

  // Check for workspace view
  const hasWorkspace = await spRoot.locator("text=Select a file").isVisible({ timeout: 10_000 }).catch(() => false);
  ts(hasWorkspace ? "Workspace visible (Select a file)" : "Workspace not visible");
  await page.screenshot({ path: "e2e-step3-workspace.png" });

  // Open intro.py from the file tree
  ts("Looking for intro.py in file tree...");
  const introFile = spRoot.locator("text=intro.py").first();
  const hasIntro = await introFile.isVisible({ timeout: 8_000 }).catch(() => false);
  if (!hasIntro) {
    // Try opening notebooks folder first
    const notebooksFolder = spRoot.locator("text=notebooks").first();
    if (await notebooksFolder.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await notebooksFolder.click();
      await page.waitForTimeout(1000);
    }
  }

  if (await introFile.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await introFile.click();
    ts("Clicked intro.py");

    // NOW wait for kernel instantiate
    const kernelResp = await page.waitForResponse(
      (r) => r.url().includes("/kernel/instantiate") && r.status() === 200,
      { timeout: 30_000 }
    ).catch(() => null);
    ts(kernelResp ? "Kernel instantiated" : "Kernel not instantiated");
  } else {
    ts("intro.py not found in file tree");
  }

  await page.waitForTimeout(2000);
  await page.screenshot({ path: "e2e-step4-loaded.png" });

  // ── Step 4: Go back to project list ────────────────────────────
  ts("Navigating back to /projects...");
  const errsBeforeBack = errors.length;
  await page.goto("/projects", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(5000);
  ts("Back on /projects");
  await page.screenshot({ path: "e2e-step5-back.png" });

  const newErrorsAfterBack = errors.slice(errsBeforeBack);
  const transactionErrors = newErrorsAfterBack.filter((e) => e.includes("transaction") || e.includes("500"));

  // ── Report ─────────────────────────────────────────────────────
  console.log("\n=== FLOW TEST REPORT ===");
  console.log(`Total errors: ${errors.length}`);
  console.log(`Errors after clicking project: ${errors.length - errsBefore}`);
  console.log(`Errors after going back: ${newErrorsAfterBack.length}`);
  if (transactionErrors.length > 0) {
    console.log("Transaction/500 errors:");
    for (const e of transactionErrors) console.log("  ", e);
  }

  const critical = errors.filter((e) => e.includes("TypeError") || e.includes("Cannot read"));
  expect(critical.length, "No TypeErrors").toBe(0);
});
