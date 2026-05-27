import { test } from "@playwright/test";

test("trace what happens between project click and workspace visible", async ({ page }) => {
  test.setTimeout(120_000);

  const t0 = Date.now();
  const ts = (label: string) => console.log(`[${((Date.now() - t0) / 1000).toFixed(2)}s] ${label}`);

  // Track ALL network requests with timing
  page.on("response", (r) => {
    const u = r.url();
    if (u.includes("localhost:3300")) {
      ts(`<< ${r.status()} ${r.request().method()} ${u.replace("http://localhost:3300", "").split("?")[0].slice(0, 80)}`);
    }
  });

  // Track console for sync and render markers
  page.on("console", (msg) => {
    const t = msg.text();
    if (t.includes("[Sync]") || t.includes("Runtime") || t.includes("Initializing") || t.includes("healthy")) {
      ts(`BROWSER: ${t.slice(0, 150)}`);
    }
  });

  // Track JS chunk loads (Turbopack compilation)
  page.on("response", (r) => {
    if (r.url().includes("_next/static/chunks") && r.status() === 200) {
      const size = r.headers()["content-length"];
      if (size && Number(size) > 50000) {
        ts(`CHUNK: ${(Number(size) / 1024).toFixed(0)}KB ${r.url().split("/").pop()?.slice(0, 50)}`);
      }
    }
  });

  ts("Navigate to /projects");
  await page.goto("/projects", { waitUntil: "domcontentloaded" });
  ts("DOMContentLoaded");

  // Wait for either existing session (running status) or landing page
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

  const spRoot = page.locator(".sp-root");
  await spRoot.waitFor({ timeout: 30_000 });
  ts("Embed visible");

  // Wait for the notebook home to render
  const projectCard = spRoot.locator("text=test").first();
  await projectCard.waitFor({ timeout: 15_000 });
  ts("Project card visible — clicking now");

  await projectCard.click();
  ts("CLICKED PROJECT");

  // Now poll rapidly for workspace indicators
  const startClick = Date.now();
  let found = false;
  for (let i = 0; i < 100; i++) {
    await page.waitForTimeout(100);
    const text = await spRoot.innerText().catch(() => "");
    if (text.includes("Select a file") || text.includes("Kernel") || text.includes("intro.py")) {
      ts(`WORKSPACE VISIBLE (${Date.now() - startClick}ms after click)`);
      found = true;
      break;
    }
  }
  if (!found) ts("Workspace not visible after 10s");
});
