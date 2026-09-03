import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";

/**
 * Covers the chat markdown renderer through the /chats/markdown playground.
 * Everything asserted here is standard markdown or standard HTML, so a
 * regression shows up as raw tag text in the transcript.
 *
 * Against a local-mode web server the page is public and the suite just runs.
 * Against a cloud-mode server /chats is Clerk-protected: mint a state file
 * (`sp-local/scripts/e2e/mint_clerk_ticket.py <email>`) and point
 * SP_E2E_STATE_FILE at it. One single-use ticket covers the whole file, since
 * every test shares one signed-in page.
 */

const BASE = process.env.SP_WEB_BASE_URL ?? "http://localhost:3200";

interface E2EState {
  org_id: string;
  sign_in_tickets?: string[];
}

const statePath = process.env.SP_E2E_STATE_FILE;
const state: E2EState | null = statePath
  ? (JSON.parse(fs.readFileSync(statePath, "utf8")) as E2EState)
  : null;

async function signIn(page: Page, s: E2EState): Promise<void> {
  const ticket = s.sign_in_tickets?.[0];
  if (!ticket) throw new Error("state file has no sign_in_tickets");
  await page.goto(`${BASE}/sign-in`);
  await page.waitForFunction(() =>
    Boolean((window as unknown as { Clerk?: { loaded?: boolean } }).Clerk?.loaded),
  );
  await page.evaluate(
    async ({ t, orgId }) => {
      const clerk = (window as unknown as { Clerk: any }).Clerk;
      const result = await clerk.client.signIn.create({
        strategy: "ticket",
        ticket: t,
      });
      await clerk.setActive({
        session: result.createdSessionId,
        organization: orgId,
      });
    },
    { t: ticket, orgId: s.org_id },
  );
  await page
    .waitForURL(/dashboard|onboarding|projects/, { timeout: 20_000 })
    .catch(() => undefined);
}

async function openSection(page: Page, id: string): Promise<void> {
  await page.goto(`${BASE}/chats/markdown`);
  // Clicks before React hydration are silently lost.
  await expect(page.getByTestId("markdown-showcase")).toHaveAttribute(
    "data-hydrated",
    "1",
  );
  await page.getByTestId(`showcase-section-${id}`).click();
}

test.describe.configure({ mode: "serial" });

test.describe("chat markdown renderer", () => {
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage({ baseURL: BASE });
    if (state) await signIn(page, state);
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("renders GFM prose, tables, task lists and footnotes", async () => {
    await openSection(page, "prose");
    const rendered = page.getByTestId("showcase-rendered");
    await expect(rendered.locator("table thead").first()).toContainText(
      "Refund rate",
    );
    await expect(rendered.locator("input[type=checkbox]").first()).toBeChecked();
    await expect(rendered.locator("blockquote")).toContainText(
      "month of the original order",
    );
    await expect(rendered.locator("sup").first()).toBeVisible();
  });

  test("renders inline HTML instead of printing the tags", async () => {
    await openSection(page, "html");
    const rendered = page.getByTestId("showcase-rendered");
    await expect(rendered.locator("kbd").first()).toBeVisible();
    await expect(rendered.locator("mark")).toContainText("unaudited");
    await expect(rendered.locator("abbr")).toHaveAttribute(
      "title",
      "Annual Recurring Revenue",
    );
    await expect(rendered.locator("dt").first()).toContainText("Freshness");
    // A hand-written table with rowspan/colspan survives sanitization.
    await expect(rendered.locator("caption")).toContainText("Refunds by channel");
    await expect(rendered.locator("th[rowspan]")).toContainText("Channel");
    await expect(rendered.locator("figcaption")).toContainText(
      "Finance definitions",
    );
    await expect(rendered).not.toContainText("<mark>");
  });

  test("dropdowns open, close, and keep their markdown", async () => {
    await openSection(page, "disclosures");
    const rendered = page.getByTestId("showcase-rendered");
    const disclosures = rendered.locator("details");
    await expect(disclosures).toHaveCount(3);

    const first = disclosures.first();
    await expect(first).not.toHaveAttribute("open", /.*/);
    await first.getByText("Assumptions and exclusions").click();
    await expect(first).toHaveAttribute("open", /.*/);
    await expect(first).toContainText("Test orders excluded");

    // `<details open>` starts expanded, with a highlighted code block inside.
    await expect(disclosures.nth(1)).toHaveAttribute("open", /.*/);
    await expect(disclosures.nth(1).locator("pre")).toContainText(
      "date_trunc",
    );

    const withTable = disclosures.nth(2);
    await withTable.getByText("Verification checks").click();
    await expect(withTable.locator("table")).toContainText("distinct keys");
  });

  test("highlights code and tints diffs, with copy on every block", async () => {
    await openSection(page, "code");
    const rendered = page.getByTestId("showcase-rendered");
    // The metastring title replaces the bare language label.
    await expect(rendered).toContainText("monthly revenue");
    await expect(rendered.locator("pre").first()).toContainText("net_revenue");
    await expect(rendered.getByRole("button", { name: "Copy" })).toHaveCount(4);
    await expect(rendered.locator("pre").last()).toContainText("r.line_id");
  });

  test("code is inset from its frame, and framed blocks are inset inside a disclosure", async () => {
    await openSection(page, "disclosures");
    const rendered = page.getByTestId("showcase-rendered");

    // The original defect: a `padding: 0` override on the framed `pre` put the
    // first character of every SQL block flush against the frame border.
    const pre = rendered.locator(".chat-md-code pre").first();
    const padding = await pre.evaluate((node) => {
      const style = getComputedStyle(node);
      return {
        left: Number.parseFloat(style.paddingLeft),
        top: Number.parseFloat(style.paddingTop),
      };
    });
    expect(padding.left).toBeGreaterThanOrEqual(8);
    expect(padding.top).toBeGreaterThanOrEqual(6);

    // A code frame inside an open <details> keeps a gutter on both sides
    // rather than butting up against the disclosure border.
    const open = rendered.locator("details[open]").first();
    const gutters = await open.evaluate((node) => {
      const frame = node.querySelector(".chat-md-code");
      if (!frame) return null;
      const outer = node.getBoundingClientRect();
      const inner = frame.getBoundingClientRect();
      return { left: inner.left - outer.left, right: outer.right - inner.right };
    });
    expect(gutters).not.toBeNull();
    expect(gutters!.left).toBeGreaterThanOrEqual(8);
    expect(gutters!.right).toBeGreaterThanOrEqual(8);
  });

  test("renders mermaid diagrams and typeset math", async () => {
    await openSection(page, "diagrams");
    const rendered = page.getByTestId("showcase-rendered");
    await expect(rendered.locator(".chat-md-mermaid svg")).toHaveCount(2);
    await expect(rendered.locator(".chat-md-mermaid").first()).toContainText(
      "fct_orders",
    );
    await expect(rendered.locator(".katex").first()).toBeVisible();
    // Currency stays currency: no stray formula around the dollar amounts.
    await expect(rendered).toContainText("$1,000 refund");
  });

  test("streaming never leaves half-parsed markup on screen", async () => {
    await openSection(page, "disclosures");
    await page.getByTestId("showcase-stream").click();
    const rendered = page.getByTestId("showcase-rendered");
    for (let tick = 0; tick < 6; tick += 1) {
      await expect(rendered).not.toContainText("<summary>");
      await page.waitForTimeout(120);
    }
    await expect(rendered.locator("details")).toHaveCount(3);
  });
});
