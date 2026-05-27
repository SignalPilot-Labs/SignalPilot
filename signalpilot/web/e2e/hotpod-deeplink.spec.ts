import { test } from "@playwright/test";

const URL = "/projects?project=3781d00d-3f10-4139-9b70-2e4cd9c42c63&branch=main&file=intro.py";

test("hot pod deep-link: what blocks what", async ({ page }) => {
  test.setTimeout(60_000);

  const t0 = Date.now();
  const ts = (l: string) => console.log(`[${((Date.now() - t0) / 1000).toFixed(2)}s] ${l}`);

  page.on("response", (r) => {
    const u = r.url();
    if (u.includes("localhost:3300/notebook")) {
      ts(`<< ${r.status()} ${r.request().method()} ${u.replace(/http:\/\/localhost:3300\/notebook\/[^/]+/, "").split("?")[0]}`);
    }
  });
  page.on("console", (msg) => {
    const t = msg.text();
    if (t.includes("Sync") || t.includes("Runtime") || t.includes("Initializing") || t.includes("healthy") || t.includes("sync-gate")) {
      ts(`LOG: ${t.slice(0, 120)}`);
    }
  });

  ts("navigate");
  await page.goto(URL, { waitUntil: "domcontentloaded" });
  ts("DOMContentLoaded");

  // Wait for running status
  await page.getByText("running").waitFor({ timeout: 30_000 }).catch(() => {});
  ts("running visible");

  const spRoot = page.locator(".sp-root");
  await spRoot.waitFor({ timeout: 30_000 }).catch(() => {});
  ts(".sp-root");

  // Poll for specific UI milestones
  const start = Date.now();
  let sawFiles = false, sawContent = false, sawKernel = false;

  for (let i = 0; i < 200 && Date.now() - start < 30000; i++) {
    await page.waitForTimeout(100);
    const text = await spRoot.innerText().catch(() => "");

    if (!sawFiles && (text.includes("notebooks") || text.includes("models") || text.includes("intro.py"))) {
      ts("FILE TREE visible");
      sawFiles = true;
    }
    if (!sawContent && (text.includes("Welcome") || text.includes("import signalpilot"))) {
      ts("FILE CONTENT visible (intro.py loaded)");
      sawContent = true;
    }
    if (!sawKernel && text.includes("Kernel")) {
      // Check if kernel shows as connected vs loading
      const hasUnlink = await spRoot.locator("svg.lucide-unlink").isVisible().catch(() => false);
      ts(hasUnlink ? "KERNEL indicator: disconnected" : "KERNEL indicator: visible");
      sawKernel = true;
    }
    if (sawFiles && sawContent) break;
  }

  if (!sawFiles) ts("FILE TREE: never appeared");
  if (!sawContent) ts("FILE CONTENT: never appeared");

  await page.screenshot({ path: "e2e-hotpod-deeplink.png" });
  ts("done");
});
