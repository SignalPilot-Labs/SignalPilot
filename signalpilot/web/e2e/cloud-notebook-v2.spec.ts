/**
 * Cloud-mode E2E for Notebook Runtime v2 (sessionless boot + lazy kernel).
 *
 * Runs against the staging-shaped local stack (gateway in cloud mode, real
 * Clerk, real workspace S3, real Vercel sandboxes):
 *
 *   SP_E2E_STATE_FILE=../../../sp-local/scripts/e2e/state.json \
 *   PLAYWRIGHT_BASE_URL=http://localhost:3000 \
 *     pnpm exec playwright test cloud-notebook-v2 --reporter=line
 *
 * Verifies the v2 contract end to end:
 *   1. Opening a project notebook creates NO runtime session — the editor and
 *      file plane come straight from the gateway workspace store.
 *   2. The first Run lazily provisions a Vercel sandbox and executes.
 *   3. Saving persists a durable revision; reload replays without a kernel.
 *
 * Creates a scratch project (e2e-nbv2-*) and deletes it at the end.
 */

import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";

interface E2EState {
  gateway_url: string;
  org_id: string;
  email: string;
  password: string;
  sign_in_tickets?: string[];
}

const statePath = process.env.SP_E2E_STATE_FILE;
const state: E2EState | null = statePath
  ? (JSON.parse(
      fs.readFileSync(statePath, "utf8").replace(/^﻿/, ""),
    ) as E2EState)
  : null;

test.skip(!state, "SP_E2E_STATE_FILE not set — cloud E2E stack not running");
test.describe.configure({ mode: "serial" });
test.setTimeout(300_000);

async function signIn(page: Page, s: E2EState): Promise<void> {
  await page.goto("/sign-in");
  await page.waitForFunction(() => Boolean((window as any).Clerk?.loaded));
  const ticket = s.sign_in_tickets?.shift();
  if (ticket) {
    await page.evaluate(
      async ({ t, orgId }) => {
        const Clerk = (window as any).Clerk;
        const res = await Clerk.client.signIn.create({ strategy: "ticket", ticket: t });
        await Clerk.setActive({ session: res.createdSessionId, organization: orgId });
      },
      { t: ticket, orgId: s.org_id },
    );
    // Settle on an authenticated page before making in-page gateway calls —
    // Clerk may navigate after setActive, aborting in-flight loads/fetches.
    await page.waitForTimeout(1500);
    await page
      .goto("/dashboard", { waitUntil: "domcontentloaded" })
      .catch(() => page.goto("/dashboard", { waitUntil: "domcontentloaded" }));
    await page.waitForFunction(() => Boolean((window as any).Clerk?.session), {
      timeout: 30_000,
    });
    await dismissTierCelebration(page);
    return;
  }
  throw new Error("No sign-in ticket — re-run mint_clerk_ticket.py");
}

/** Close the tier-upgrade celebration ("Enterprise is active.") if shown.
 * It can pop in late (after the subscription loads), so poll for a while and
 * fall back to Escape (the dialog supports Esc-dismiss). */
async function dismissTierCelebration(page: Page, windowMs = 8000): Promise<void> {
  const deadline = Date.now() + windowMs;
  while (Date.now() < deadline) {
    const headline = page.getByText(/is active\./).first();
    if (await headline.isVisible({ timeout: 1000 }).catch(() => false)) {
      const close = page.getByRole("button", { name: "Dismiss" }).first();
      if (await close.isVisible({ timeout: 500 }).catch(() => false)) {
        await close.click().catch(() => {});
      } else {
        await page.keyboard.press("Escape").catch(() => {});
      }
      await page.waitForTimeout(700);
      return;
    }
    await page.waitForTimeout(500);
  }
}

/** Authenticated gateway call from inside the page (real Clerk token). */
async function gw<T>(
  page: Page,
  s: E2EState,
  path: string,
  init?: { method?: string; body?: unknown },
): Promise<T> {
  return page.evaluate(
    async ({ base, p, method, body }) => {
      const token = await (window as any).Clerk.session.getToken();
      const res = await fetch(base + p, {
        method: method ?? "GET",
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      if (res.status === 204) return null;
      if (!res.ok) throw new Error(`${p}: ${res.status} ${await res.text()}`);
      return res.json();
    },
    { base: s.gateway_url, p: path, method: init?.method, body: init?.body },
  ) as Promise<T>;
}

const scratchName = `e2e-nbv2-${Date.now().toString(36)}`;
let projectId = "";

test("sessionless open → lazy Vercel run → save → reload replay", async ({ page }) => {
  const s = state!;
  const errors: string[] = [];
  const diagnostics: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/kernel/") || req.url().includes("/api/document/")) {
      console.log("[E2E net]", req.method(), req.url().slice(-90));
    }
  });
  page.on("requestfailed", (req) => {
    console.log("[E2E net-FAILED]", req.method(), req.url().slice(-90), req.failure()?.errorText);
  });
  page.on("pageerror", (err) => {
    console.log("[E2E pageerror]", err.message.slice(0, 300));
    errors.push(`PAGE: ${err.message.slice(0, 300)}`);
  });
  page.on("console", (msg) => {
    const t = msg.text();
    if (t.includes("[provision]") || t.includes("[lazy-requests]") || t.includes("[doc-sync]") || t.includes("handleKernelReady") || t.includes("parse failed") || t.includes("sessionless")) {
      console.log("[E2E diag]", t.slice(0, 300));
      diagnostics.push(t.slice(0, 200));
    }
    if (msg.type() !== "error") return;
    const url = msg.location()?.url ?? "";
    if (/\/connections\/[^/]+\/schema/.test(url)) return;
    console.log("[E2E console-error]", t.slice(0, 300), url.slice(-80));
    errors.push(`CONSOLE: ${t.slice(0, 300)} [${url.slice(-80)}]`);
  });

  await signIn(page, s);

  // Shared staging account: clear any manual session so the sessionless
  // assertion below sees only what THIS page does.
  await gw(page, s, "/api/notebook-sessions", { method: "DELETE" }).catch(() => {});
  await page.waitForTimeout(1000);

  // ── Scratch project ────────────────────────────────────────────
  const project = await gw<{ id: string }>(page, s, "/api/workspace-projects", {
    method: "POST",
    body: { name: scratchName, display_name: scratchName, source: "managed" },
  });
  projectId = project.id;
  expect(projectId).toBeTruthy();

  // ── 1. Sessionless open: editor mounts with NO runtime session ─
  await page.goto(
    `/projects?project=${projectId}&branch=main&file=__new__notebook`,
    { waitUntil: "domcontentloaded" },
  );
  await dismissTierCelebration(page);
  await page.locator(".cm-editor").first().waitFor({ timeout: 30_000 });

  await page.waitForTimeout(1000);
  const sessionAfterOpen = await gw<unknown>(page, s, "/api/notebook-sessions");
  console.log("DIAGNOSTICS(open):\n" + diagnostics.join("\n"));
  expect(
    sessionAfterOpen,
    `opening the editor must not create a runtime session, got: ${JSON.stringify(sessionAfterOpen)?.slice(0, 200)}`,
  ).toBeFalsy();

  // ── 2. Type + first Run provisions the Vercel sandbox lazily ───
  await dismissTierCelebration(page, 2000);
  const cm = page.locator(".cm-editor").first().locator(".cm-content");
  await cm.click();
  await page.keyboard.type('print("hello staging v2")', { delay: 20 });
  await page.waitForTimeout(500);
  const runClickedAt = Date.now();
  await page.keyboard.press("Control+Enter");

  const output = page.locator("[data-testid=console-output-area]");
  await expect(output.first()).toContainText("hello staging v2", {
    timeout: 180_000,
  });
  console.log(
    `TIMING run→output: ${((Date.now() - runClickedAt) / 1000).toFixed(1)}s (cold sandbox provisioned lazily)`,
  );

  const sessionAfterRun = await gw<{ status?: string } | null>(
    page, s, "/api/notebook-sessions",
  );
  expect(sessionAfterRun?.status, "first Run must provision a session").toBe("running");

  // ── 3. Save (names the notebook), verify a durable revision ────
  await page.keyboard.press("Control+s");
  await page.getByText("Save notebook").waitFor({ timeout: 10_000 });
  await page.locator("dialog input, [role=dialog] input").first().fill("hello_v2.py");
  await page.keyboard.press("Enter");

  // Write-through is async; poll the store until the .py lands.
  let saved: { path: string } | undefined;
  let lastListing: string[] = [];
  for (let i = 0; i < 15 && !saved; i++) {
    await page.waitForTimeout(2000);
    const list = await gw<{ files?: Array<{ path: string }> }>(
      page, s, `/api/workspace-projects/${projectId}/files:list`,
      { method: "POST", body: { branch: "main" } },
    );
    lastListing = (list.files ?? []).map((f) => f.path);
    saved = (list.files ?? []).find((f) => f.path.endsWith("hello_v2.py"));
  }
  expect(saved, `hello_v2.py in store, got: ${lastListing.join(", ")}`).toBeTruthy();

  console.log("DIAGNOSTICS:\n" + diagnostics.join("\n"));
  const fatal = errors.filter((e) => e.includes("TypeError") || e.includes("500 "));
  expect(fatal, `no fatal errors: ${fatal.join(" | ")}`).toHaveLength(0);

  // ── 4. Reload replay (kill the session first: replay must be kernel-free)
  await gw(page, s, "/api/notebook-sessions", { method: "DELETE" });
  await page.goto(
    `/projects?project=${projectId}&branch=main&file=${encodeURIComponent(saved!.path)}`,
    { waitUntil: "domcontentloaded" },
  );
  await page.locator(".cm-editor").first().waitFor({ timeout: 30_000 });
  await page.waitForTimeout(2000);
  const text = await page.locator(".sp-root").innerText();
  if (!text.includes("hello staging v2")) {
    console.log("[E2E reload-page-text]", text.replace(/\s+/g, " ").slice(0, 500));
  }
  expect(text).toContain("hello staging v2");

  const sessionAfterReload = await gw<unknown>(page, s, "/api/notebook-sessions");
  expect(sessionAfterReload, "reload must not provision a session").toBeFalsy();

  // ── Cleanup ────────────────────────────────────────────────────
  await gw(page, s, `/api/workspace-projects/${projectId}`, { method: "DELETE" });
  // Let the DELETE settle before Playwright tears the page down (an aborted
  // request leaks the scratch project).
  await page.waitForTimeout(1500);
});
