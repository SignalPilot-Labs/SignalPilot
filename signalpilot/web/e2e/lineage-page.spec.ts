/**
 * dbt map page (/lineage): schema window, canvas, inspector, provenance.
 * Same cloud-stack state file as cloud-github-import — skips without it.
 */

import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";

interface E2EState {
  gateway_url: string;
  org_id: string;
  sign_in_tickets?: string[];
  email: string;
  password: string;
}

const statePath = process.env.SP_E2E_STATE_FILE;
const state: E2EState | null = statePath
  ? (JSON.parse(fs.readFileSync(statePath, "utf8")) as E2EState)
  : null;

test.skip(!state, "SP_E2E_STATE_FILE not set — cloud E2E stack not running");
test.setTimeout(120_000);

async function signIn(page: Page, s: E2EState): Promise<void> {
  await page.goto("/sign-in");
  await page.waitForFunction(() => Boolean((window as any).Clerk?.loaded));
  const ticket = s.sign_in_tickets?.shift();
  if (!ticket) throw new Error("state.json has no unused sign_in_tickets");
  await page.evaluate(
    async ({ t, orgId }) => {
      const Clerk = (window as any).Clerk;
      const res = await Clerk.client.signIn.create({ strategy: "ticket", ticket: t });
      await Clerk.setActive({ session: res.createdSessionId, organization: orgId });
    },
    { t: ticket, orgId: s.org_id },
  );
  await page
    .waitForURL(/dashboard|onboarding|projects/, { timeout: 20_000 })
    .catch(() => page.goto("/dashboard", { waitUntil: "domcontentloaded" }).catch(() => {}));
}

test("dbt map renders schema window, canvas, and inspector", async ({ page }) => {
  const s = state!;
  await signIn(page, s);

  await page.goto("/lineage");
  await expect(page.getByRole("heading", { name: "dbt map" })).toBeVisible({ timeout: 20_000 });

  // A fresh session may show the tier upgrade celebration dialog — dismiss it
  // or it intercepts every click on the page.
  const celebration = page.getByRole("button", { name: "Dismiss" });
  if (await celebration.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await celebration.click();
  }

  // Graph loads (nodes on canvas) — the map for dumpsters-demo is compiled.
  await expect(page.locator(".react-flow__node").first()).toBeVisible({ timeout: 30_000 });
  const nodeCount = await page.locator(".react-flow__node").count();
  expect(nodeCount).toBeGreaterThan(5);

  // Schema window lists schemas with model rows.
  await expect(page.getByText("schemas", { exact: true })).toBeVisible();

  // Provenance + auto-update affordances.
  await expect(page.getByText(/compiled .* ago|compiling on sandbox/)).toBeVisible();
  await expect(page.getByText(/auto · push/)).toBeVisible();

  // Legend shows fixed-order layers with counts.
  await expect(page.getByText(/nodes · .* edges/)).toBeVisible();

  // The celebration dialog can mount seconds later (after the tier fetch) —
  // sweep again before interacting.
  await page.waitForTimeout(2500);
  if (await celebration.isVisible().catch(() => false)) {
    await celebration.click();
  }

  // Select via the schema window (stable target — canvas nodes re-render on
  // hover for path dimming) -> inspector drawer opens with lineage lists.
  await page.locator("div.w-60 button.font-mono").first().click();
  await expect(page.getByText(/upstream|downstream|columns/).first()).toBeVisible({
    timeout: 10_000,
  });

  // Visual artifact for design review (kept on pass, not just failure).
  await page.setViewportSize({ width: 1720, height: 980 });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: "test-results/lineage-page.png", fullPage: false });
});
