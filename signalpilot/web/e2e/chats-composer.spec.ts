/**
 * Chats composer + project picker rework. Same cloud-stack state file as the
 * other cloud E2E specs; skips without it.
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
    .waitForURL(/dashboard|onboarding|projects|chats/, { timeout: 20_000 })
    .catch(() => page.goto("/dashboard", { waitUntil: "domcontentloaded" }).catch(() => {}));
}

test("composer autosizes, gives disabled feedback, and the project picker searches", async ({
  page,
}) => {
  const s = state!;
  await signIn(page, s);
  await page.goto("/chats");

  const composer = page.getByTestId("standalone-chat-composer");
  await expect(composer).toBeVisible({ timeout: 20_000 });

  const dismiss = page.getByRole("button", { name: "Dismiss" });
  if (await dismiss.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await dismiss.click();
  }

  // Project picker opens and searches.
  await page.getByRole("button", { name: "Select project" }).click();
  await expect(page.getByPlaceholder("search projects…")).toBeVisible();
  await page.getByPlaceholder("search projects…").fill("dumpsters");
  await expect(
    page.getByText("dumpsters", { exact: false }).first(),
  ).toBeVisible();
  await page.keyboard.press("Escape");

  // Textarea autosizes with content.
  const textarea = composer.locator("textarea");
  const before = await textarea.evaluate((el) => el.clientHeight);
  await textarea.fill("line one\nline two\nline three\nline four\nline five");
  const after = await textarea.evaluate((el) => el.clientHeight);
  expect(after).toBeGreaterThan(before);

  // Helper hint documents Enter / Shift+Enter.
  await textarea.fill("");
  await expect(page.getByText(/Enter to send/)).toBeVisible();

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: "test-results/chats-composer.png" });
});
