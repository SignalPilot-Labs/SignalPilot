import { test, expect } from "@playwright/test";

const GATEWAY = "http://localhost:3300";
const PROJECT = "c90eacbf-3f69-45d3-a7e9-2bff3266ede7";
const URL = `/projects?project=${PROJECT}&branch=main&file=intro.py`;

test("cold start — no pod, deep-link URL auto-launches and loads file", async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);

  const keyRes = await request.get("http://localhost:3200/api/local-key");
  const apiKey = (await keyRes.json()).key;

  const t0 = Date.now();
  const ts = (label: string) => {
    const s = ((Date.now() - t0) / 1000).toFixed(2);
    console.log(`[${s}s] ${label}`);
    return Number(s);
  };

  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text().slice(0, 200));
  });

  // ── Kill everything — truly cold start ─────────────────────────
  ts("Killing session...");
  await request.delete(`${GATEWAY}/api/notebook-sessions`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  });
  await page.waitForTimeout(15000);
  ts("Cleanup done");

  // ── Navigate to deep-link URL ──────────────────────────────────
  // With the fix, this should immediately show the loading overlay
  // ("connecting to pod") — no "Open IDE" button at all.
  const tNav = ts("Navigating to deep-link URL");
  await page.goto(URL, { waitUntil: "domcontentloaded" });
  const tPageLoad = ts("Page loaded");

  // Should show the starting overlay, NOT the landing page
  const startingOverlay = page.getByText(/connecting|creating session|starting kernel|syncing/i);
  const hasOverlay = await startingOverlay.isVisible({ timeout: 5000 }).catch(() => false);
  ts(hasOverlay ? "Loading overlay visible (no landing page)" : "No overlay — checking state...");

  // Wait for "running" status
  const runningText = page.getByText("running");
  await expect(runningText).toBeVisible({ timeout: 90_000 });
  const tRunning = ts("Session running");

  // Wait for .sp-root
  const spRoot = page.locator(".sp-root");
  await expect(spRoot).toBeAttached({ timeout: 15_000 });
  const tEmbed = ts("Embed attached");

  // Wait for kernel
  const instResp = await page.waitForResponse(
    (r) => r.url().includes("/kernel/instantiate") && r.status() === 200,
    { timeout: 60_000 }
  ).catch(() => null);
  const tKernel = instResp ? ts("Kernel instantiate 200") : ts("Kernel instantiate NOT called");

  // Wait for file content
  await page.waitForTimeout(3000);
  const text = await spRoot.innerText().catch(() => "");
  const hasContent = text.includes("Welcome") || text.includes("import") || text.includes("intro");
  const tContent = ts(hasContent ? "File content visible" : "No file content");

  await page.screenshot({ path: "e2e-cold-start.png" });

  // ── Report ─────────────────────────────────────────────────────
  console.log("\n" + "=".repeat(60));
  console.log("COLD START TIMING REPORT");
  console.log("=".repeat(60));
  console.log(`  Page load:          ${(tPageLoad - tNav).toFixed(2)}s`);
  console.log(`  Pod creation:       ${(tRunning - tNav).toFixed(2)}s`);
  console.log(`  Embed mount:        ${(tEmbed - tRunning).toFixed(2)}s`);
  console.log(`  Kernel spawn:       ${(tKernel - tEmbed).toFixed(2)}s`);
  console.log(`  File visible:       ${(tContent - tKernel).toFixed(2)}s`);
  console.log(`  ─────────────────────────────────`);
  console.log(`  TOTAL (nav → file): ${(tContent - tNav).toFixed(2)}s`);

  if (errors.length > 0) {
    const critical = errors.filter((e) => e.includes("TypeError") || e.includes("500"));
    if (critical.length > 0) {
      console.log(`\n  Critical errors: ${critical.length}`);
      for (const e of critical.slice(0, 3)) console.log("    ", e);
    }
  }

  expect(hasContent, "File content should be visible").toBe(true);
  expect(
    errors.filter((e) => e.includes("TypeError")).length,
    "No TypeErrors"
  ).toBe(0);
});
