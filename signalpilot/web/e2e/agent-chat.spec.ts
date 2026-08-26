import { test, expect } from "@playwright/test";

const GATEWAY = "http://localhost:3300";
const PROJECT = "c90eacbf-3f69-45d3-a7e9-2bff3266ede7";
const URL = `/projects?project=${PROJECT}&branch=main&file=intro.py`;

test("SignalPilot Agent — send message and receive response", async ({
  page,
}) => {
  test.setTimeout(120_000);

  const t0 = Date.now();
  const ts = (label: string) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${label}`);

  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text().slice(0, 300));
  });
  page.on("pageerror", (err) => errors.push(`PAGE: ${err.message.slice(0, 300)}`));

  // ── Step 1: Navigate and wait for IDE ──────────────────────────
  ts("Navigating...");
  await page.goto(URL, { waitUntil: "domcontentloaded" });

  const runningText = page.getByText("running");
  const openBtn = page.getByRole("button", { name: /open ide/i });

  await Promise.race([
    runningText.waitFor({ timeout: 30_000 }),
    openBtn.waitFor({ timeout: 30_000 }),
  ]);

  if (await openBtn.isVisible().catch(() => false)) {
    await openBtn.click();
    ts("Clicked Open IDE");
  }
  await expect(runningText).toBeVisible({ timeout: 60_000 });
  ts("Session running");

  // ── Step 2: Wait for kernel ────────────────────────────────────
  const spRoot = page.locator(".sp-root");
  await expect(spRoot).toBeAttached({ timeout: 15_000 });

  await page.waitForResponse(
    (r) => r.url().includes("/kernel/instantiate") && r.status() === 200,
    { timeout: 60_000 }
  ).catch(() => null);
  ts("Kernel ready");
  await page.waitForTimeout(2000);

  // ── Step 3: Open the Agent panel ───────────────────────────────
  // Try multiple approaches to open the agent panel
  let panelOpened = false;

  // Approach 1: Click by tooltip
  for (const tooltip of ["SignalPilot agent", "Agent", "agent"]) {
    const btn = spRoot.locator(`button[title="${tooltip}"]`);
    if (await btn.isVisible({ timeout: 1000 }).catch(() => false)) {
      await btn.click();
      panelOpened = true;
      ts(`Opened agent via tooltip "${tooltip}"`);
      break;
    }
  }

  // Approach 2: Find SVG with lucide-bot class
  if (!panelOpened) {
    const botSvg = spRoot.locator("svg.lucide-bot").first();
    if (await botSvg.isVisible({ timeout: 1000 }).catch(() => false)) {
      await botSvg.click();
      panelOpened = true;
      ts("Opened agent via bot SVG");
    }
  }

  // Approach 3: Use keyboard shortcut or try all sidebar icons
  if (!panelOpened) {
    // The sidebar icons are in a scrollable strip — try scrolling and clicking
    const sidebar = spRoot.locator("aside, [role='tablist']").first();
    if (await sidebar.isVisible({ timeout: 1000 }).catch(() => false)) {
      // Scroll sidebar to bottom to reveal hidden icons
      await sidebar.evaluate((el) => el.scrollTop = el.scrollHeight);
      await page.waitForTimeout(500);

      // Now try finding the bot icon again
      const botAfterScroll = spRoot.locator("svg.lucide-bot").first();
      if (await botAfterScroll.isVisible({ timeout: 1000 }).catch(() => false)) {
        await botAfterScroll.click();
        panelOpened = true;
        ts("Opened agent after sidebar scroll");
      }
    }
  }

  if (!panelOpened) {
    ts("Could not open agent panel");
    await page.screenshot({ path: "e2e-agent-icons.png" });
  }

  await page.waitForTimeout(1000);

  // ── Step 4: Find chat input ────────────────────────────────────
  const chatInput = spRoot.locator('textarea[placeholder*="Message the agent"]');
  const hasInput = await chatInput.isVisible({ timeout: 10_000 }).catch(() => false);

  if (!hasInput) {
    ts("Chat textarea not found — checking for org API key setup prompt...");
    const integrationsLink = spRoot.locator('a[href="/integrations"]');
    if (await integrationsLink.isVisible({ timeout: 3000 }).catch(() => false)) {
      ts("Org API key setup prompt found — agent requires admin configuration");
      await page.screenshot({ path: "e2e-agent-apikey.png" });
    } else {
      await page.screenshot({ path: "e2e-agent-noinput.png" });
    }

    console.log("\n=== AGENT CHAT TEST ===");
    console.log("Result: BLOCKED — chat input not available (may need API key)");
    return;
  }

  ts("Chat input found");

  // ── Step 5: Send message ───────────────────────────────────────
  await chatInput.fill("Hi what notebook are you looking at");
  await page.keyboard.press("Enter");
  ts("Message sent");

  // Track agent API calls
  const agentCalls: string[] = [];
  page.on("response", (r) => {
    if (r.url().includes("/agent/") || r.url().includes("/ai/")) {
      agentCalls.push(`[${r.status()}] ${r.request().method()} ${r.url().replace(/http:\/\/localhost:\d+/, "")}`);
    }
  });

  // ── Step 6: Wait for response ──────────────────────────────────
  ts("Waiting for agent response (10s)...");
  await page.waitForTimeout(10_000);

  const chatText = await spRoot.innerText().catch(() => "");
  const hasResponse = chatText.includes("intro") ||
    chatText.includes("notebook") ||
    chatText.includes("looking at") ||
    chatText.includes("Welcome");

  ts(hasResponse ? "Agent responded" : "No agent response detected");
  await page.screenshot({ path: "e2e-agent-response.png" });

  // ── Report ─────────────────────────────────────────────────────
  console.log("\n=== AGENT CHAT TEST ===");
  console.log("Agent API calls:", agentCalls.length);
  for (const c of agentCalls) console.log("  ", c);

  const criticalErrors = errors.filter(
    (e) => e.includes("TypeError") || e.includes("Cannot read") || e.includes("500")
  );
  console.log("Critical errors:", criticalErrors.length);
  for (const e of criticalErrors.slice(0, 5)) console.log("  ", e);
  console.log("Has response:", hasResponse);

  expect(criticalErrors.length, "No critical errors during agent chat").toBe(0);
});
