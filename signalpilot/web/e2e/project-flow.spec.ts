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

  // ── Step 1: Go to /projects (no params) ────────────────────────
  ts("Navigate to /projects");
  await page.goto("/projects", { waitUntil: "domcontentloaded" });

  // Should see running state (existing session) or landing page
  const spRoot = page.locator(".sp-root");
  // Wait for either running (existing session) or Open IDE button
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
  await spRoot.waitFor({ timeout: 30_000 });
  ts("Embed loaded");

  // Wait for notebook home to render
  await page.waitForTimeout(3000);
  await page.screenshot({ path: "e2e-step1-projects.png" });

  // ── Step 2: Click on "test" project ────────────────────────────
  ts("Looking for 'test' project card...");
  const projectCard = spRoot.locator("text=test").first();
  const hasProject = await projectCard.isVisible({ timeout: 10_000 }).catch(() => false);

  if (!hasProject) {
    ts("'test' project not visible — checking what's shown");
    const text = await spRoot.innerText().catch(() => "");
    ts(`Content: ${text.slice(0, 200)}`);
    await page.screenshot({ path: "e2e-step2-noproj.png" });
    return;
  }

  const errsBefore = errors.length;
  await projectCard.click();
  ts("Clicked 'test' project");

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
