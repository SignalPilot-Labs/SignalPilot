/**
 * Close-up visual audit of the chat composer. Captures tight screenshots of
 * just the composer element in several states so layout bugs (double borders,
 * misalignment, overflow) are visible.
 */

import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";

interface E2EState {
  gateway_url: string;
  org_id: string;
  sign_in_tickets?: string[];
}

const statePath = process.env.SP_E2E_STATE_FILE;
const state: E2EState | null = statePath
  ? (JSON.parse(fs.readFileSync(statePath, "utf8")) as E2EState)
  : null;

test.skip(!state, "SP_E2E_STATE_FILE not set");
test.setTimeout(120_000);

async function signIn(page: Page, s: E2EState): Promise<void> {
  await page.goto("/sign-in");
  await page.waitForFunction(() => Boolean((window as any).Clerk?.loaded));
  const ticket = s.sign_in_tickets?.shift();
  if (!ticket) throw new Error("no ticket");
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
    .catch(() => page.goto("/dashboard").catch(() => {}));
}

test("composer close-up states", async ({ page }) => {
  const s = state!;
  await signIn(page, s);
  await page.goto("/chats");
  const composer = page.getByTestId("standalone-chat-composer");
  await expect(composer).toBeVisible({ timeout: 20_000 });
  const dismiss = page.getByRole("button", { name: "Dismiss" });
  if (await dismiss.isVisible({ timeout: 2_000 }).catch(() => false)) await dismiss.click();

  // Empty-state full page: composer should be front-and-center, big legible
  // heading, comfortable palette.
  await page.screenshot({ path: "test-results/chats-empty-full.png" });

  const textarea = composer.locator("textarea");

  // Placeholder legibility: empty + focused, plus computed ::placeholder opacity.
  await textarea.click();
  await page.waitForTimeout(150);
  const phOpacity = await textarea.evaluate((el) =>
    getComputedStyle(el, "::placeholder").opacity,
  );
  console.log("PLACEHOLDER_OPACITY:", phOpacity);
  const box0 = await composer.boundingBox();
  if (box0) {
    await page.screenshot({
      path: "test-results/composer-placeholder-focused.png",
      clip: { x: box0.x - 8, y: box0.y - 8, width: box0.width + 16, height: box0.height + 16 },
    });
  }

  // FOCUSED + TYPING via real keyboard (triggers :focus-visible). Full-page
  // screenshot + a tight clip that INCLUDES margin around the composer, so an
  // outline drawn OUTSIDE the element box is captured (element.screenshot()
  // clips it off — that was the earlier miss).
  await textarea.click();
  await page.keyboard.type("What were total revenues by month last quarter?");
  await page.waitForTimeout(200);
  const box = await composer.boundingBox();
  if (box) {
    await page.screenshot({
      path: "test-results/composer-focused.png",
      clip: {
        x: Math.max(0, box.x - 12),
        y: Math.max(0, box.y - 12),
        width: box.width + 24,
        height: box.height + 24,
      },
    });
  }

  // Report outline + box-shadow + border of the textarea AND its ancestors
  // WHILE focused — outline is the channel element-screenshots hide.
  const focusReport = await textarea.evaluate((ta) => {
    const rows: any[] = [];
    let el: Element | null = ta;
    for (let i = 0; i < 4 && el; i++) {
      const cs = getComputedStyle(el);
      rows.push({
        tag: el.tagName.toLowerCase(),
        focused: el === document.activeElement,
        outline: `${cs.outlineWidth} ${cs.outlineStyle} ${cs.outlineColor}`,
        boxShadow: cs.boxShadow.slice(0, 60),
        border: `${cs.borderTopWidth} ${cs.borderTopColor}`,
      });
      el = el.parentElement;
    }
    return rows;
  });
  console.log("FOCUS_REPORT:", JSON.stringify(focusReport, null, 2));

  // Report the composed box geometry for layered-border detection.
  const report = await composer.evaluate((root) => {
    const walk = (el: Element, depth: number): any[] => {
      const cs = getComputedStyle(el);
      const out: any[] = [];
      if (cs.borderTopWidth !== "0px" || cs.borderRadius !== "0px" || cs.boxShadow !== "none") {
        out.push({
          depth,
          tag: el.tagName.toLowerCase(),
          cls: (el.getAttribute("class") || "").slice(0, 60),
          border: cs.borderTopWidth,
          borderColor: cs.borderTopColor,
          radius: cs.borderRadius,
          shadow: cs.boxShadow.slice(0, 40),
        });
      }
      for (const child of Array.from(el.children)) out.push(...walk(child, depth + 1));
      return out;
    };
    return walk(root, 0);
  });
  console.log("BORDERED_ELEMENTS:", JSON.stringify(report, null, 2));
});
