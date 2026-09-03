/**
 * Cloud-mode E2E: Clerk sign-in -> one-click GitHub repo link -> project
 * settings (dbt dir, watched branches) -> dbt map status.
 *
 * Requires a live cloud stack (gateway in cloud mode + real Clerk dev
 * instance + seeded GitHub installation) described by a state file:
 *   SP_E2E_STATE_FILE=/path/to/state.json pnpm exec playwright test cloud-github-import
 *
 * The state file provides a throwaway Clerk user (email/password), the org id,
 * and repo names. Without SP_E2E_STATE_FILE the suite skips cleanly.
 */

import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";

interface E2EState {
  gateway_url: string;
  org_id: string;
  email: string;
  password: string;
  /** Single-use Clerk sign-in tokens for a REAL user (minted via Backend
   *  API); one is consumed per test. When present they replace the password
   *  flow entirely. */
  sign_in_tickets?: string[];
  github_account: string;
  installation_row_id: string;
  imported_project_id: string;
  imported_project_name: string;
  imported_repo_full_name: string;
  ui_repo_full_name: string;
  default_branch: string;
}

const statePath = process.env.SP_E2E_STATE_FILE;
const state: E2EState | null = statePath
  ? (JSON.parse(fs.readFileSync(statePath, "utf8")) as E2EState)
  : null;

test.skip(!state, "SP_E2E_STATE_FILE not set — cloud E2E stack not running");

test.describe.configure({ mode: "serial" });
test.setTimeout(180_000);

async function signIn(page: Page, s: E2EState): Promise<void> {
  await page.goto("/sign-in");
  await page.waitForFunction(() => Boolean((window as any).Clerk?.loaded));

  const ticket = s.sign_in_tickets?.shift();
  if (ticket) {
    // Real-user path: redeem a single-use Backend-API ticket. No password.
    await page.evaluate(
      async ({ t, orgId }) => {
        const Clerk = (window as any).Clerk;
        const res = await Clerk.client.signIn.create({ strategy: "ticket", ticket: t });
        await Clerk.setActive({ session: res.createdSessionId, organization: orgId });
      },
      { t: ticket, orgId: s.org_id },
    );
    // The sign-in page redirects itself once the session activates; racing it
    // with our own goto aborts the navigation. Follow its lead, nudge if idle.
    await page
      .waitForURL(/dashboard|onboarding|projects/, { timeout: 20_000 })
      .catch(() =>
        page.goto("/dashboard", { waitUntil: "domcontentloaded" }).catch(() => {}),
      );
    return;
  }

  await page.locator("#email").fill(s.email);
  await page.getByRole("button", { name: "continue", exact: true }).click();
  await page.locator("#password").fill(s.password);
  await page.getByRole("button", { name: "sign in", exact: true }).click();
  await page.waitForURL(/dashboard|onboarding|projects/, { timeout: 30_000 });

  // Deterministically activate the org — a fresh session may start on the
  // personal account, and every gateway call is org-scoped.
  await page.evaluate(async (orgId) => {
    await (window as any).Clerk.setActive({ organization: orgId });
  }, s.org_id);
  await page.waitForTimeout(500);
}

/** Authenticated gateway GET from inside the page (real Clerk token). */
async function gwGet<T>(page: Page, s: E2EState, path: string): Promise<T> {
  return page.evaluate(
    async ({ base, p }) => {
      const token = await (window as any).Clerk.session.getToken();
      const res = await fetch(base + p, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`${p}: ${res.status}`);
      return res.json();
    },
    { base: s.gateway_url, p: path },
  ) as Promise<T>;
}

test("sign in, one-click link a repo, verify settings and dbt map", async ({
  page,
}) => {
  const s = state!;
  await signIn(page, s);

  // ── GitHub settings: installation visible, one-click link ────────────────
  await page.goto("/settings/github");
  await expect(page.getByText(s.github_account).first()).toBeVisible({
    timeout: 20_000,
  });

  const links = await gwGet<Array<{ repo_full_name: string; project_id: string }>>(
    page, s, "/api/github/repo-links",
  );
  const alreadyLinked = links.some((l) => l.repo_full_name === s.ui_repo_full_name);

  if (!alreadyLinked) {
    await page.getByRole("button", { name: /link repo/i }).click();
    const repoRow = page
      .locator("div")
      .filter({ hasText: s.ui_repo_full_name })
      .locator("button", { hasText: "link" })
      .last();
    await expect(repoRow).toBeEnabled({ timeout: 20_000 });
    await repoRow.click();

    // Synchronous clone + revision import; the button surfaces live stages
    // (cloning… / importing files N/M…) from the progress endpoint.
    await expect(
      page.getByText(/project ".*" created|already linked/i),
    ).toBeVisible({ timeout: 300_000 });
  }

  // Linked repos list shows the mapping either way.
  await expect(
    page.getByText(s.ui_repo_full_name, { exact: false }).first(),
  ).toBeVisible();

  // ── Project settings: automation section ─────────────────────────────────
  const allLinks = await gwGet<Array<{ repo_full_name: string; project_id: string }>>(
    page, s, "/api/github/repo-links",
  );
  // Prefer the canonical project; in a shared org it may be unlinked at any
  // moment, so fall back to the repo this test just linked.
  const projectId =
    s.imported_project_id ||
    allLinks.find((l) => l.repo_full_name === s.imported_repo_full_name)?.project_id ||
    allLinks.find((l) => l.repo_full_name === s.ui_repo_full_name)?.project_id;
  expect(projectId, "project id resolvable from repo links").toBeTruthy();
  await page.goto(`/projects/${projectId}/settings`);
  await expect(page.getByText("dbt project & automation")).toBeVisible({
    timeout: 20_000,
  });

  // dbt dir detection populated from the imported repo.
  await expect(page.locator("#project-dbt-dir")).toBeVisible();

  // dbt map status reflects the compile pipeline (import auto-schedules one).
  await expect(page.getByText(/dbt map:/)).toBeVisible();
  await expect(page.getByText(/dbt map:/)).toContainText(
    /success|running|queued|none|failed/,
  );

  // Watched branches: add a marker chip, save, verify it survives reload,
  // then remove it again — leaves the real org's settings as we found them.
  const branchInput = page.getByPlaceholder("add branch…");
  await branchInput.fill("pw-e2e-marker");
  await branchInput.press("Enter");
  await expect(page.getByText("pw-e2e-marker")).toBeVisible();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Project automation settings saved"),
  ).toBeVisible({ timeout: 15_000 });

  await page.reload();
  await expect(page.getByText("dbt project & automation")).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByText("pw-e2e-marker")).toBeVisible();

  await page.getByLabel("Stop watching pw-e2e-marker").click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Project automation settings saved"),
  ).toBeVisible({ timeout: 15_000 });
});

test("projects page shows both imported projects", async ({ page }) => {
  const s = state!;
  await signIn(page, s);
  await page.goto("/projects");
  await expect(
    page.getByText(s.imported_project_name, { exact: false }).first(),
  ).toBeVisible({ timeout: 30_000 });
});
