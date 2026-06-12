import { test, expect } from "@playwright/test";

const GATEWAY = "http://localhost:3300";
const PROJECT = "c90eacbf-3f69-45d3-a7e9-2bff3266ede7";
const BRANCH = "main";
const FILE = "intro.py";
const URL = `/projects?project=${PROJECT}&branch=${BRANCH}&file=${FILE}`;

test("deep-link load: open file, kernel connect, run cells", async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);

  // ── Get API key ────────────────────────────────────────────────
  const keyRes = await request.get("http://localhost:3200/api/local-key");
  const apiKey = (await keyRes.json()).key;

  // ── Timers ─────────────────────────────────────────────────────
  const t0 = Date.now();
  const ts = (label: string) => {
    const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
    console.log(`[${elapsed}s] ${label}`);
  };

  // ── Capture everything ─────────────────────────────────────────
  const errors: string[] = [];
  const warnings: string[] = [];
  const network: string[] = [];
  const failed: string[] = [];

  page.on("console", (msg) => {
    const text = msg.text();
    if (msg.type() === "error") errors.push(text.slice(0, 300));
    if (msg.type() === "warning") warnings.push(text.slice(0, 300));
    if (text.includes("[sync-gate]") || text.includes("[edit-app]") || text.includes("[Sync]")) {
      console.log(`  BROWSER: ${text}`);
    }
  });
  page.on("pageerror", (err) => errors.push(`PAGE: ${err.message.slice(0, 300)}`));
  page.on("response", (r) => {
    if (r.url().includes("localhost:3300")) {
      network.push(`[${r.status()}] ${r.request().method()} ${r.url().replace("http://localhost:3300", "")}`);
    }
  });
  page.on("requestfailed", (r) => {
    failed.push(`${r.method()} ${r.url().slice(0, 200)} — ${r.failure()?.errorText}`);
  });

  // ── Step 1: Navigate to deep-link URL ──────────────────────────
  ts("Navigating to " + URL);
  await page.goto(URL);
  ts("Page loaded (DOMContentLoaded)");

  // The page should detect no session and show "Open IDE"
  // OR detect an existing session and show "running"
  const openBtn = page.getByRole("button", { name: /open ide/i });
  const runningText = page.getByText("running");

  const hasSession = await runningText.isVisible({ timeout: 5000 }).catch(() => false);
  if (!hasSession) {
    ts("No running session — clicking Open IDE");
    await expect(openBtn).toBeVisible({ timeout: 10_000 });
    await openBtn.click();
    ts("Clicked Open IDE, waiting for session...");
    await expect(runningText).toBeVisible({ timeout: 60_000 });
  }
  ts("Session running");

  // ── Step 2: Wait for .sp-root (embed mount) ────────────────────
  const spRoot = page.locator(".sp-root");
  await expect(spRoot).toBeAttached({ timeout: 15_000 });
  ts(".sp-root attached");

  // ── Step 3: Wait for runtime healthy ───────────────────────────
  // The health check hits the gateway; watch for the 200
  await page.waitForResponse(
    (r) => r.url().includes("/health") && r.status() === 200,
    { timeout: 30_000 }
  );
  ts("Runtime healthy (health check 200)");

  // ── Step 4: Wait for kernel instantiate ────────────────────────
  const instantiateResp = page.waitForResponse(
    (r) => r.url().includes("/kernel/instantiate"),
    { timeout: 60_000 }
  ).catch(() => null);

  const kernelResp = await instantiateResp;
  if (kernelResp) {
    ts(`Kernel instantiate: ${kernelResp.status()}`);
  } else {
    ts("⚠️ kernel/instantiate never called");
  }

  // ── Step 5: Wait for WebSocket connection ──────────────────────
  // Check for the unlink icon (disconnected) vs connected state
  await page.waitForTimeout(5000);
  const disconnected = await spRoot.locator("svg.lucide-unlink").isVisible().catch(() => false);
  ts(disconnected ? "⚠️ Kernel DISCONNECTED (unlink icon visible)" : "✅ Kernel connected");

  // ── Step 6: Check if file content loaded ───────────────────────
  const bodyText = await spRoot.innerText().catch(() => "");
  const hasFileContent =
    bodyText.includes("Welcome") ||
    bodyText.includes("sp.init") ||
    bodyText.includes("import") ||
    bodyText.includes("intro");
  ts(hasFileContent ? "✅ File content loaded" : "⚠️ File content not visible");

  // ── Step 7: Try running cells ──────────────────────────────────
  if (!disconnected && hasFileContent) {
    ts("Running all cells (Ctrl+Shift+R)...");
    await page.keyboard.press("Control+Shift+r");
    await page.waitForTimeout(8000);

    const outputText = await spRoot.innerText().catch(() => "");
    const hasOutput =
      outputText.includes("Welcome") ||
      outputText.includes("Getting started") ||
      outputText.includes("connected");
    ts(hasOutput ? "✅ Cell output rendered" : "⚠️ No cell output detected");
  }

  // ── Screenshot ─────────────────────────────────────────────────
  await page.screenshot({ path: "e2e-deep-load.png", fullPage: true });

  // ── Report ─────────────────────────────────────────────────────
  const totalSec = ((Date.now() - t0) / 1000).toFixed(1);
  console.log(`\n${"=".repeat(60)}`);
  console.log(`DEEP-LINK LOAD TEST — total ${totalSec}s`);
  console.log("=".repeat(60));

  if (errors.length > 0) {
    console.log(`\n❌ ERRORS (${errors.length}):`);
    for (const e of errors.slice(0, 15)) console.log("  ", e);
  }

  if (warnings.length > 0) {
    const wsWarnings = warnings.filter(
      (w) => w.includes("WebSocket") || w.includes("unmounting")
    );
    if (wsWarnings.length > 0) {
      console.log(`\n⚠️  WEBSOCKET WARNINGS (${wsWarnings.length}):`);
      for (const w of wsWarnings.slice(0, 10)) console.log("  ", w);
    }
  }

  if (failed.length > 0) {
    console.log(`\n🔴 FAILED REQUESTS (${failed.length}):`);
    for (const f of failed.slice(0, 10)) console.log("  ", f);
  }

  console.log(`\n📡 NOTEBOOK PROXY CALLS (${network.filter((n) => n.includes("/notebook/")).length}):`);
  for (const n of network.filter((n) => n.includes("/notebook/")).slice(0, 20)) {
    console.log("  ", n);
  }

  // ── Assertions ─────────────────────────────────────────────────
  expect(disconnected, "Kernel should be connected").toBe(false);

  const cspErrors = errors.filter((e) => e.includes("Content Security Policy"));
  expect(cspErrors.length, "No CSP violations").toBe(0);

  const typeErrors = errors.filter(
    (e) => e.includes("TypeError") || e.includes("Cannot read properties")
  );
  expect(typeErrors.length, "No runtime TypeErrors").toBe(0);
});
