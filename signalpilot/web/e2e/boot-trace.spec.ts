import { test } from "@playwright/test";

const PROJECT_ID = "3781d00d-3f10-4139-9b70-2e4cd9c42c63";
const GATEWAY = "http://localhost:3300";

test("Trace boot sequence timing", async ({ page }) => {
  test.setTimeout(120_000);

  const logs: string[] = [];
  page.on("console", (msg) => logs.push(`[${msg.type()}] ${msg.text().slice(0, 300)}`));
  page.on("pageerror", (err) => logs.push(`[PAGE_ERROR] ${err.message.slice(0, 200)}`));

  // Intercept key network requests to measure timing
  const networkEvents: { url: string; method: string; ms: number; status: number }[] = [];
  const pageStart = Date.now();

  page.on("request", (req) => {
    const url = req.url();
    if (url.includes("/notebook/") || url.includes("/api/")) {
      (req as any)._startTime = Date.now();
    }
  });
  page.on("response", (resp) => {
    const req = resp.request();
    const url = req.url();
    const start = (req as any)._startTime;
    if (start && (url.includes("/notebook/") || url.includes("/api/"))) {
      const shortUrl = url.replace(/https?:\/\/[^/]+/, "").slice(0, 80);
      networkEvents.push({
        url: shortUrl,
        method: req.method(),
        ms: Date.now() - start,
        status: resp.status(),
      });
    }
  });

  console.log("=== BOOT TRACE: Warm pod deep-link ===\n");
  const t0 = Date.now();
  const ts = () => `+${Date.now() - t0}ms`;

  console.log(`${ts()} goto starting...`);
  await page.goto(
    `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
    { waitUntil: "domcontentloaded" }
  );
  console.log(`${ts()} domcontentloaded`);

  // Poll for key milestones
  const milestones: { name: string; at: number }[] = [];
  const check = async (name: string, selector: string, timeout: number) => {
    try {
      await page.locator(selector).first().waitFor({ timeout });
      milestones.push({ name, at: Date.now() - t0 });
      console.log(`${ts()} ${name}`);
    } catch {
      console.log(`${ts()} ${name} — TIMEOUT (${timeout}ms)`);
    }
  };

  await check("SignalPilot IDE header", "text=SignalPilot IDE", 5_000);
  await check("'running' badge", "text=running", 10_000);
  await check(".sp-root", ".sp-root", 60_000);
  await check("first .cm-editor", ".cm-editor", 30_000);
  await check(".cm-focused (auto)", ".cm-focused", 3_000);
  await check(".cm-content", ".cm-content", 5_000);

  // Check what phase indicators appeared
  const phaseTexts = ["waiting for runtime", "syncing project", "clearing stale", "connecting"];
  for (const phase of phaseTexts) {
    const appeared = logs.some((l) => l.toLowerCase().includes(phase));
    if (appeared) console.log(`  Phase seen: "${phase}"`);
  }

  // Print network waterfall
  console.log(`\n=== NETWORK WATERFALL (${networkEvents.length} requests) ===`);
  for (const e of networkEvents) {
    const bar = "█".repeat(Math.min(Math.round(e.ms / 100), 30));
    console.log(`  ${e.method.padEnd(5)} ${e.status} ${String(e.ms).padStart(5)}ms ${bar} ${e.url}`);
  }

  // Print relevant console logs
  const relevant = logs.filter((l) =>
    l.includes("Runtime") || l.includes("healthy") || l.includes("init") ||
    l.includes("sync") || l.includes("session") || l.includes("boot") ||
    l.includes("connect") || l.includes("WebSocket") || l.includes("kernel") ||
    l.includes("ERROR") || l.includes("error") || l.includes("failed")
  );
  if (relevant.length > 0) {
    console.log(`\n=== RELEVANT LOGS (${relevant.length}) ===`);
    for (const l of relevant.slice(0, 30)) {
      console.log(`  ${l}`);
    }
  }

  // Summary
  console.log(`\n=== SUMMARY ===`);
  for (const m of milestones) {
    console.log(`  ${m.name}: ${m.at}ms`);
  }
  const totalNetworkMs = networkEvents.reduce((sum, e) => sum + e.ms, 0);
  console.log(`  Total network time: ${totalNetworkMs}ms across ${networkEvents.length} requests`);
  console.log(`  Total wall clock: ${Date.now() - t0}ms`);
});
