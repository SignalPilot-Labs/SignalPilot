/**
 * Lineage deep links (/lineage/<model>[/raw]): resolution by name and
 * unique_id, the not-found card with fuzzy suggestions, the raw-tables view
 * URL, and URL rewriting on focus enter/exit.
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
test.setTimeout(180_000);

async function signIn(page: Page, s: E2EState): Promise<void> {
  await page.goto("/sign-in");
  await page.waitForFunction(() => Boolean((window as any).Clerk?.loaded));
  // pop() (not shift()) — each spec file gets its own copy of state.json, so
  // taking from the far end avoids burning the same one-shot ticket as
  // lineage-page.spec.ts when both files run in one invocation.
  const ticket = s.sign_in_tickets?.pop();
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

async function dismissCelebration(page: Page): Promise<void> {
  const celebration = page.getByRole("button", { name: "Dismiss" });
  if (await celebration.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await celebration.click();
  }
}

/** Fetch the compiled dbt map through the gateway (as the app does) and pick
 *  a model whose bare name is unique — the canonical deep-link form. */
async function pickModel(
  page: Page,
  gatewayUrl: string,
): Promise<{ name: string; uniqueId: string }> {
  return page.evaluate(async (gw) => {
    const Clerk = (window as any).Clerk;
    const token = await Clerk.session.getToken();
    const auth = { Authorization: `Bearer ${token}` };
    const projRes = await fetch(`${gw}/api/workspace-projects?status=active`, { headers: auth });
    const { projects } = (await projRes.json()) as { projects: any[] };
    const remembered = localStorage.getItem("sp:lineage-project");
    const pid = projects.find((p: any) => p.id === remembered)?.id ?? projects[0].id;
    const mapRes = await fetch(`${gw}/api/workspace-projects/${pid}/dbt-map`, { headers: auth });
    const { graph } = (await mapRes.json()) as { graph: any };
    const nodes: Record<string, any> = graph?.nodes ?? {};
    const counts: Record<string, number> = {};
    for (const [id, n] of Object.entries(nodes)) {
      if (id.startsWith("model.") && n.name) counts[n.name] = (counts[n.name] ?? 0) + 1;
    }
    const entry = Object.entries(nodes).find(
      ([id, n]) => id.startsWith("model.") && n.name && counts[n.name] === 1,
    );
    if (!entry) throw new Error("no uniquely-named model in the compiled map");
    return { name: entry[1].name as string, uniqueId: entry[0] };
  }, gatewayUrl);
}

test("deep links: name + unique_id resolution, raw view, not-found, URL rewrite", async ({ page }) => {
  const s = state!;
  await signIn(page, s);

  // The tier celebration dialog can mount at any time after the tier fetch
  // and intercepts every click — auto-dismiss it whenever it appears.
  await page.addLocatorHandler(
    page.getByRole("button", { name: "Dismiss" }),
    async (btn) => {
      await btn.click().catch(() => {});
    },
  );

  // Load the full map once so the project bootstrap has run.
  await page.goto("/lineage");
  await expect(page.getByRole("heading", { name: "dbt map" })).toBeVisible({ timeout: 20_000 });
  await dismissCelebration(page);
  await expect(page.locator(".react-flow__node").first()).toBeVisible({ timeout: 30_000 });
  const model = await pickModel(page, s.gateway_url);

  // 1. Deep link by bare name -> focus mode with staged captions.
  await page.goto(`/lineage/${model.name}`);
  await dismissCelebration(page);
  const chip = page.getByTestId("focus-chip");
  await expect(chip).toBeVisible({ timeout: 30_000 });
  await expect(chip).toContainText(model.name);
  // Stage captions render on the canvas (at least one stage label present).
  await expect(page.getByText(/^(Sources|Staging|Intermediate|Dims \/ Facts|Marts)$/).first()).toBeVisible();

  // 2. Deep link by full unique_id resolves to the same focus.
  await page.goto(`/lineage/${encodeURIComponent(model.uniqueId)}`);
  await dismissCelebration(page);
  await expect(page.getByTestId("focus-chip")).toContainText(model.name, { timeout: 30_000 });
  // The URL is rewritten to the canonical bare-name form.
  await expect
    .poll(() => page.evaluate(() => window.location.pathname), { timeout: 15_000 })
    .toBe(`/lineage/${encodeURIComponent(model.name)}`);

  // 3. /raw opens the Raw Tables panel and the URL keeps the qualifier.
  await page.goto(`/lineage/${model.name}/raw`);
  await dismissCelebration(page);
  await expect(page.getByTestId("focus-chip")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "raw tables" })).toBeVisible();
  await expect(
    page.getByText(/tables? feeds? |No raw source tables feed this model directly\./).first(),
  ).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(`/lineage/${encodeURIComponent(model.name)}/raw`);

  // 4. Unknown model -> not-found card, bad URL stays put, full-map escape.
  const typo = `${model.name}zz`;
  await page.goto(`/lineage/${typo}`);
  await dismissCelebration(page);
  await expect(page.getByText(`No model named`, { exact: false })).toBeVisible({ timeout: 30_000 });
  // Fuzzy suggestion for the near-miss name links to the real model.
  await expect(page.getByText("Did you mean").first()).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(`/lineage/${encodeURIComponent(typo)}`);
  await page.getByRole("button", { name: "Show full map" }).click();
  await expect(page.getByTestId("focus-chip")).toHaveCount(0);
  await expect
    .poll(() => page.evaluate(() => window.location.pathname))
    .toBe("/lineage");

  // 5. Entering focus from the map rewrites the URL; Escape rewrites it back.
  await dismissCelebration(page);
  await page.locator("div.w-60 button.font-mono").first().click();
  await page.getByRole("button", { name: "Focus", exact: true }).click();
  await expect(page.getByTestId("focus-chip")).toBeVisible({ timeout: 15_000 });
  await expect
    .poll(() => page.evaluate(() => window.location.pathname))
    .not.toBe("/lineage");
  await page.keyboard.press("Escape");
  await expect
    .poll(() => page.evaluate(() => window.location.pathname))
    .toBe("/lineage");

  // Visual artifact for design review.
  await page.goto(`/lineage/${model.name}/raw`);
  await dismissCelebration(page);
  await expect(page.getByTestId("focus-chip")).toBeVisible({ timeout: 30_000 });
  await page.setViewportSize({ width: 1720, height: 980 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: "test-results/lineage-raw-view.png", fullPage: false });
});
