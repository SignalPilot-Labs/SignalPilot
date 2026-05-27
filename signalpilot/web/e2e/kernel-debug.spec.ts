import { test, expect } from "@playwright/test";

const GATEWAY_URL = "http://localhost:3300";

test("kernel connection — open project file and check for errors", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);

  const keyRes = await request.get("http://localhost:3200/api/local-key");
  const apiKey = (await keyRes.json()).key;

  // Clean up old session
  await request.delete(`${GATEWAY_URL}/api/notebook-sessions`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  });
  await page.waitForTimeout(3000);

  // Capture everything
  const allConsole: string[] = [];
  const allNetwork: string[] = [];
  const failedRequests: string[] = [];

  page.on("console", (msg) => {
    allConsole.push(`[${msg.type()}] ${msg.text()}`);
  });
  page.on("pageerror", (err) => {
    allConsole.push(`[PAGE_ERROR] ${err.message}`);
  });
  page.on("response", (resp) => {
    const u = resp.url();
    if (u.includes("localhost:3300")) {
      allNetwork.push(
        `[${resp.status()}] ${resp.request().method()} ${u.replace("http://localhost:3300", "")}`
      );
    }
  });
  page.on("requestfailed", (req) => {
    failedRequests.push(
      `[FAIL] ${req.method()} ${req.url()} — ${req.failure()?.errorText}`
    );
  });

  // Step 1: Launch IDE and create a project with scaffold
  await page.goto("/projects");
  await page.getByRole("button", { name: /open ide/i }).click();
  await expect(page.getByText("running")).toBeVisible({ timeout: 45_000 });

  const spRoot = page.locator(".sp-root");
  await expect(spRoot).toBeAttached({ timeout: 15_000 });

  // Wait for Create Project button
  const createBtn = spRoot.getByRole("button", { name: /create new project/i });
  await expect(createBtn).toBeVisible({ timeout: 15_000 });
  await createBtn.click();
  await page.waitForTimeout(500);

  const nameInput = spRoot.getByPlaceholder("my_dbt_project");
  await expect(nameInput).toBeVisible({ timeout: 5000 });
  await nameInput.fill("e2e_test");

  // Create and wait for full scaffold
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.waitForResponse(
    (r) => r.url().includes("/git/push") && r.status() === 200,
    { timeout: 60_000 }
  );
  console.log("[1] ✅ Project created and scaffolded");

  // Step 2: Wait for workspace navigation, then wait 10s for kernel
  await page.waitForTimeout(10_000);
  console.log("[2] Waited 10s after scaffold");

  // Step 3: Check kernel status
  const unlinkIcon = spRoot.locator("svg.lucide-unlink");
  const isDisconnected = await unlinkIcon.isVisible().catch(() => false);
  console.log("[3] Kernel disconnected icon:", isDisconnected);

  // Check for "Not connected" or "kernel" text
  const notConnected = await spRoot
    .locator("text=Not connected")
    .isVisible()
    .catch(() => false);
  const kernelNotReady = await spRoot
    .locator("text=Kernel not ready")
    .isVisible()
    .catch(() => false);
  console.log("[3] 'Not connected':", notConnected);
  console.log("[3] 'Kernel not ready':", kernelNotReady);

  await page.screenshot({ path: "e2e-kernel-state.png" });

  // Dump diagnostics
  console.log("\n=== ERRORS ===");
  const errors = allConsole.filter(
    (l) => l.startsWith("[error]") || l.startsWith("[PAGE_ERROR]")
  );
  for (const e of errors.slice(0, 15)) console.log(e.slice(0, 300));

  console.log("\n=== FAILED REQUESTS ===");
  for (const f of failedRequests) console.log(f.slice(0, 300));

  console.log("\n=== WEBSOCKET / KERNEL LOGS ===");
  const wsLogs = allConsole.filter(
    (l) =>
      l.toLowerCase().includes("websocket") ||
      l.toLowerCase().includes("kernel") ||
      l.toLowerCase().includes("instantiate") ||
      l.includes("ws://") ||
      l.includes("wss://") ||
      l.includes("CONNECTING") ||
      l.includes("connection")
  );
  for (const w of wsLogs.slice(0, 20)) console.log(w.slice(0, 300));

  console.log("\n=== RUNTIME LOGS ===");
  const rtLogs = allConsole.filter(
    (l) => l.includes("Runtime") || l.includes("⚡")
  );
  for (const r of rtLogs) console.log(r.slice(0, 300));

  console.log("\n=== GATEWAY 4xx/5xx ===");
  const gatewayErrors = allNetwork.filter((n) =>
    n.match(/^\[(4|5)\d\d\]/)
  );
  for (const g of gatewayErrors) console.log(g);

  console.log("\n=== ALL NOTEBOOK PROXY CALLS ===");
  const proxyCalls = allNetwork.filter((n) => n.includes("/notebook/"));
  for (const p of proxyCalls.slice(0, 30)) console.log(p);
});
