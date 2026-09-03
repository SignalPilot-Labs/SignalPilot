import { expect, test, type Page } from "@playwright/test";

/**
 * /settings/connectors against the in-memory fixture (?fixture=1): the
 * list, the three-step add flow (URL and command), tool switches and bulk
 * actions, the drawer tabs, and the remove dialog. No gateway needed.
 */

const BASE = process.env.SP_WEB_BASE_URL ?? "http://localhost:3200";
const SETTINGS = `${BASE}/settings/connectors?fixture=1`;

async function openDrawer(page: Page, name: string) {
  await page.getByTestId("connector-row").filter({ hasText: name }).getByTestId("connector-row-open").click();
  await expect(page.getByTestId("connector-drawer")).toBeVisible();
}

test.describe("connectors settings page (fixture)", () => {
  test("renders both sections with health, tool counts, real glyphs, and the policy row below", async ({ page }) => {
    await page.goto(SETTINGS);
    await expect(page.getByRole("heading", { name: "Connectors" })).toBeVisible();
    await expect(page.getByText("Warehouse connections live under Connections.")).toBeVisible();
    const org = page.getByTestId("connectors-section-org");
    await expect(org.getByTestId("connector-row")).toHaveCount(3);
    await expect(org).toContainText("Jira");
    await expect(org).toContainText("mcp.atlassian.com");
    const personal = page.getByTestId("connectors-section-personal");
    await expect(personal.getByTestId("connector-row")).toHaveCount(2);
    // One health value per row, from the stories' state table.
    const jira = org.getByTestId("connector-row").filter({ hasText: "Jira" });
    await expect(jira.getByTestId("connector-status-pill")).toHaveText("Connected");
    await expect(jira.getByTestId("connector-row-tools")).toHaveText("10 tools · 5 on");
    const slack = org.getByTestId("connector-row").filter({ hasText: "Slack" });
    await expect(slack.getByTestId("connector-status-pill")).toHaveText("Tools changed");
    await expect(slack.getByTestId("connector-row-detail")).toHaveText("3 new tools since last check");
    const linear = personal.getByTestId("connector-row").filter({ hasText: "Linear" });
    await expect(linear.getByTestId("connector-status-pill")).toHaveText("Unreachable");
    await expect(linear.getByRole("button", { name: "Retry" })).toBeVisible();
    // Glyphs: curated marks for known hosts, never a bare letter for the fixtures.
    await expect(jira.getByTestId("connector-glyph")).toHaveAttribute("data-glyph", "brand:atlassian");
    await expect(slack.getByTestId("connector-glyph")).toHaveAttribute("data-glyph", "brand:slack");
    await expect(org.getByTestId("connector-row").filter({ hasText: "Snowflake" }).getByTestId("connector-glyph")).toHaveAttribute("data-glyph", "icon");
    // The org policy is a collapsed row below the Personal section, not the first thing on screen.
    const policy = page.getByTestId("org-policy-card");
    await expect(policy).toBeVisible();
    await expect(policy).toHaveAttribute("data-open", "false");
    await expect(policy.getByTestId("org-policy-summary")).toHaveText("Members can add personal connectors · any host");
    const policyBox = await policy.boundingBox();
    const personalBox = await personal.boundingBox();
    expect(policyBox!.y).toBeGreaterThan(personalBox!.y + personalBox!.height - 1);
    // Never protocol words (or the banned "inject") in primary copy.
    const body = await page.locator("main").innerText();
    expect(body).not.toMatch(/\b(OAuth|transport|endpoint|MCP|inject\w*)\b/);
  });

  test("the first row's kebab menu is fully visible and clickable (portal, not clipped)", async ({ page }) => {
    await page.goto(SETTINGS);
    const first = page.getByTestId("connectors-section-org").getByTestId("connector-row").first();
    await first.getByTestId("connector-row-menu").click();
    const menu = page.getByRole("menu");
    await expect(menu).toBeVisible();
    for (const label of ["Tools", "Access", "Activity", "Turn off for everyone", "Remove…"]) {
      const item = page.getByRole("menuitem", { name: label });
      await expect(item).toBeVisible();
      // The item is the element actually under its own center: nothing paints over it.
      const box = await item.boundingBox();
      const hit = await page.evaluate(
        ([x, y]) => document.elementFromPoint(x, y)?.closest("[role=menuitem]")?.textContent ?? null,
        [box!.x + box!.width / 2, box!.y + box!.height / 2],
      );
      expect(hit).toBe(label);
    }
    // Clicking the last item on the first row acts on that row, not the one beneath it.
    await page.getByRole("menuitem", { name: "Remove…" }).click();
    await expect(page.getByTestId("confirm-dialog")).toContainText("Remove Jira for everyone?");
    await expect(page.getByTestId("confirm-dialog")).toContainText("3 members are signed in.");
    await page.getByRole("button", { name: "Cancel" }).click();
    // Keyboard: Tab closes the menu.
    await first.getByTestId("connector-row-menu").click();
    await expect(page.getByRole("menu")).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("menu")).toHaveCount(0);
  });

  test("rows are accessible: the name is a button and the switch is a sibling, one switch per scope", async ({ page }) => {
    await page.goto(SETTINGS);
    const jira = page.getByTestId("connector-row").filter({ hasText: "Jira" });
    await expect(jira).not.toHaveAttribute("role", "button");
    await expect(jira.getByTestId("connector-row-open")).toHaveAttribute("aria-label", /Jira, Connected/);
    await expect(jira.getByTestId("connector-row-on-for-me")).toHaveAttribute("role", "switch");
    // Personal rows carry the connector's own "On", never a redundant "On for me".
    const github = page.getByTestId("connector-row").filter({ hasText: "GitHub" });
    await expect(github.getByTestId("connector-row-enabled")).toHaveAttribute("aria-checked", "true");
    await expect(github.getByTestId("connector-row-on-for-me")).toHaveCount(0);
    await expect(github).toContainText("On");
    await github.getByTestId("connector-row-enabled").click();
    await expect(github.getByTestId("connector-status-pill")).toHaveText("Off");
    await expect(page.getByText("GitHub turned off")).toBeVisible();
  });

  test("members see a read-only org section, plain settings rows, and no policy row", async ({ page }) => {
    await page.goto(`${SETTINGS}&admin=0`);
    await expect(page.getByTestId("org-policy-card")).toHaveCount(0);
    await expect(page.getByTestId("connectors-section-org")).toContainText("Provided by your organization");
    await expect(page.getByTestId("connectors-add-org")).toHaveCount(0);
    await openDrawer(page, "Jira");
    await page.getByTestId("connector-tab-settings").click();
    const readonly = page.getByTestId("drawer-settings-readonly");
    await expect(readonly).toContainText("Managed by your admin");
    await expect(readonly.locator("input")).toHaveCount(0);
    await expect(page.getByTestId("drawer-settings-scope")).toHaveText("Everyone in Acme Analytics");
    await expect(page.getByTestId("drawer-settings-remove")).toHaveCount(0);
  });

  test("empty state invites the first connector", async ({ page }) => {
    await page.goto(`${SETTINGS}&empty=1`);
    await expect(page.getByTestId("connectors-empty")).toContainText("No connectors yet");
    await page.getByTestId("connectors-add-first").click();
    await expect(page.getByTestId("add-connector-modal")).toBeVisible();
  });

  test("the On-for-me switch is a real switch and persists through the fixture API", async ({ page }) => {
    await page.goto(SETTINGS);
    const jira = page.getByTestId("connector-row").filter({ hasText: "Jira" });
    const toggle = jira.getByTestId("connector-row-on-for-me");
    await expect(toggle).toHaveAttribute("role", "switch");
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    // 44px touch target on the dense switch.
    const box = await toggle.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(44);
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await expect(jira.getByTestId("connector-status-pill")).toHaveText("Off");
    await expect(jira.getByTestId("connector-row-detail")).toHaveText("Turned off by you");
    await expect(page.getByText("Jira is off for you · applies to new chats")).toBeVisible();
    // Keyboard: Space toggles it back.
    await toggle.focus();
    await page.keyboard.press("Space");
    await expect(toggle).toHaveAttribute("aria-checked", "true");
  });

  test("add flow: URL → detected sign-in → tools → connect → honest done state → sign in", async ({ page }) => {
    await page.goto(SETTINGS);
    await page.getByTestId("connectors-add").click();
    const modal = page.getByTestId("add-connector-modal");
    await expect(modal).toContainText("step 1 of 3");
    await expect(page.getByTestId("add-progress").locator("[data-state=current]")).toHaveCount(1);
    await page.getByTestId("add-source-input").fill("https://mcp.vendor.example/mcp");
    await expect(page.getByTestId("add-source-mode-url")).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId("add-sandbox-warning")).toHaveCount(0);
    await page.getByTestId("add-continue").click();
    await expect(page.getByTestId("add-probing")).toBeVisible();
    // Step 2: access pre-selected from the probe.
    await expect(modal).toContainText("step 2 of 3");
    await expect(page.getByTestId("add-access-oauth")).toHaveAttribute("aria-checked", "true");
    await expect(modal).toContainText("detected from the server");
    await page.getByTestId("add-continue").click();
    // Step 3: probed name, slug preview, R3 defaults, scope selector for admins — defaulting to Only me.
    await expect(page.getByTestId("add-name")).toHaveValue("Vendor Docs");
    await expect(modal).toContainText("mcp__vendor_docs__");
    await expect(page.getByTestId("add-scope-org")).toBeEnabled();
    await expect(page.getByTestId("add-scope-personal")).toHaveAttribute("aria-checked", "true");
    const switches = page.getByTestId("add-tools-list").getByTestId("tool-switch");
    await expect(switches).toHaveCount(4);
    await expect(switches.nth(0)).toHaveAttribute("aria-checked", "true");
    await expect(switches.nth(3)).toHaveAttribute("aria-checked", "false");
    await expect(page.getByTestId("add-tools-on").getByTestId("tool-row")).toHaveCount(3);
    await expect(page.getByTestId("add-tools-off").getByTestId("tool-row")).toHaveCount(1);
    await page.getByTestId("add-connect").click();
    // Done: the screen says "Needs sign-in" everywhere, never "Connected" early.
    const done = page.getByTestId("add-done");
    await expect(done).toContainText("Sign in to Vendor Docs");
    await expect(page.getByTestId("add-eyebrow")).toHaveText("Needs sign-in");
    await expect(page.getByTestId("add-done-pill")).toHaveText("Needs sign-in");
    await expect(page.getByTestId("add-progress").locator("[data-state=half]")).toHaveCount(1);
    await expect(page.getByTestId("add-done-slug")).toContainText("mcp__vendor_docs__");
    await expect(page.getByText(/Vendor Docs is ready · applies to new chats/)).toHaveCount(0);
    // Body says "applies to new chats" once: the footer only.
    expect(await done.innerText()).not.toMatch(/Applies to new chats/);
    await page.getByTestId("add-done-sign-in").click();
    await expect(done).toContainText("Vendor Docs is ready");
    await expect(page.getByTestId("add-eyebrow")).toHaveText("Ready");
    await expect(page.getByTestId("add-progress").locator("[data-state=done]")).toHaveCount(3);
    await expect(page.getByText("Vendor Docs is ready · applies to new chats")).toBeVisible();
    await page.getByTestId("add-finish").click();
    const row = page.getByTestId("connector-row").filter({ hasText: "Vendor Docs" });
    await expect(row).toBeVisible();
    await expect(row.getByTestId("connector-status-pill")).toHaveText("Connected");
  });

  test("add flow: a command flips to sandbox mode with the short warning, env rows, and no Key option", async ({ page }) => {
    await page.goto(SETTINGS);
    await page.getByTestId("connectors-add-org").click();
    await page.getByTestId("add-source-input").fill("npx -y @modelcontextprotocol/server-github");
    await expect(page.getByTestId("add-source-mode-command")).toHaveAttribute("aria-checked", "true");
    const warning = page.getByTestId("add-sandbox-warning");
    await expect(warning).toContainText("Runs inside your sandbox");
    await expect(warning).toContainText("including any keys");
    await expect(warning).not.toContainText("deployment");
    await expect(warning).not.toContainText("tool permissions");
    await page.getByTestId("add-continue").click();
    await expect(page.getByTestId("add-probing")).toContainText("Starting the command");
    await expect(page.getByTestId("add-access-oauth")).toHaveCount(0);
    await expect(page.getByTestId("add-access-key")).toHaveCount(0);
    await expect(page.getByTestId("add-env-name").first()).toHaveValue("GITHUB_PERSONAL_ACCESS_TOKEN");
    // Org scope: the secret must be per member.
    await expect(page.getByText("per member")).toBeVisible();
    await page.getByTestId("add-continue").click();
    // Brand casing, and the tool-permissions sentence lives where it is actionable.
    await expect(page.getByTestId("add-name")).toHaveValue("GitHub");
    await expect(page.getByTestId("add-connector-modal")).toContainText("enforced by the agent's tool permissions, not by SignalPilot");
    await page.getByTestId("add-scope-personal").click();
    await page.getByTestId("add-name").fill("My GitHub");
    await page.getByTestId("add-connect").click();
    await expect(page.getByTestId("add-eyebrow")).toHaveText("Needs your key");
    await expect(page.getByTestId("add-done")).toContainText("Add your key from the Access tab");
    // The primary action is the fix: it lands on the Access tab.
    await page.getByTestId("add-done-add-key").click();
    await expect(page.getByTestId("connector-drawer")).toContainText("My GitHub");
    await expect(page.getByTestId("connector-tab-access")).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("Escape");
    const row = page.getByTestId("connector-row").filter({ hasText: "My GitHub" });
    await expect(row.getByTestId("connector-status-pill")).toHaveText("Needs your key");
  });

  test("add flow: an unreachable address ends with one Try again and Save anyway", async ({ page }) => {
    await page.goto(SETTINGS);
    await page.getByTestId("connectors-add").click();
    await page.getByTestId("add-source-input").fill("https://nowhere.example/mcp");
    await page.getByTestId("add-continue").click();
    const error = page.getByTestId("add-probe-error");
    await expect(error).toContainText("We couldn't reach this address");
    await expect(error.getByText("Try again")).toHaveCount(0);
    await expect(page.getByTestId("add-continue")).toHaveText("Try again");
    await page.getByTestId("add-probe-save-anyway").click();
    await expect(page.getByTestId("add-connector-modal")).toContainText("step 2 of 3");
  });

  test("add flow refuses docker with a specific reason, said once", async ({ page }) => {
    await page.goto(SETTINGS);
    await page.getByTestId("connectors-add").click();
    await page.getByTestId("add-source-input").fill("docker run -i mcp/github");
    const modal = page.getByTestId("add-connector-modal");
    await expect(modal.getByRole("alert")).toContainText("Docker can't run inside the sandbox");
    await expect(page.getByTestId("add-footer-note")).toHaveText("");
    expect((await modal.innerText()).match(/Docker can't run/g)).toHaveLength(1);
    await expect(page.getByTestId("add-continue")).toBeDisabled();
  });

  test("add modal traps focus", async ({ page }) => {
    await page.goto(SETTINGS);
    await page.getByTestId("connectors-add").click();
    const modal = page.getByTestId("add-connector-modal");
    await expect(page.getByTestId("add-source-input")).toBeFocused();
    for (let i = 0; i < 12; i += 1) {
      await page.keyboard.press("Tab");
      const inside = await page.evaluate(() => Boolean(document.activeElement?.closest("[data-testid=add-connector-modal]")));
      expect(inside).toBe(true);
    }
    await expect(modal).toBeVisible();
  });

  test("drawer: tools tab groups On/Off by kind, filters by kind, switches toggle with Undo, bulk actions work", async ({ page }) => {
    await page.goto(SETTINGS);
    await openDrawer(page, "Slack");
    await expect(page.getByTestId("drawer-tools-new-banner")).toContainText("3 added · 1 removed since last check");
    const on = page.getByTestId("drawer-tools-on");
    const off = page.getByTestId("drawer-tools-off");
    await expect(on.getByTestId("tool-row")).toHaveCount(4);
    await expect(off.getByTestId("tool-row")).toHaveCount(5);
    // New tools lead the Off list and carry the chip; the destructive one comes first among them.
    await expect(off.getByTestId("tool-row").first()).toContainText("New");
    await expect(off.getByTestId("tool-row").first()).toHaveAttribute("data-tool", "delete_message");
    // Kind chips carry counts and narrow both groups.
    await expect(page.getByTestId("drawer-tools-kind-destructive")).toContainText("1");
    await page.getByTestId("drawer-tools-kind-read").click();
    await expect(off.getByTestId("tool-row")).toHaveCount(0);
    await expect(on.getByTestId("tool-row")).toHaveCount(4);
    await page.getByTestId("drawer-tools-kind-all").click();
    // Turn one on: it moves to the On group, with an Undo.
    await off.locator("[data-tool=schedule_message]").getByTestId("tool-switch").click();
    await expect(on.locator("[data-tool=schedule_message]")).toBeVisible();
    const toast = page.getByTestId("toast").filter({ hasText: "schedule_message turned on · applies to new chats" });
    await expect(toast).toBeVisible();
    await toast.getByTestId("toast-action").click();
    await expect(off.locator("[data-tool=schedule_message]")).toBeVisible();
    // Bulk: off all, then read-only on.
    await page.getByTestId("drawer-tools-off-all").click();
    await expect(on.getByTestId("tool-row")).toHaveCount(0);
    await page.getByTestId("drawer-tools-on-read-only").click();
    await expect(on.getByTestId("tool-row")).toHaveCount(4);
    // Search narrows both groups.
    await page.getByTestId("drawer-tools-search").fill("profile");
    await expect(on.getByTestId("tool-row")).toHaveCount(1);
    await expect(off).toContainText('No tools match "profile"');
  });

  test("drawer: turning on a destructive tool asks inline first and warns with Undo", async ({ page }) => {
    await page.goto(SETTINGS);
    await openDrawer(page, "Slack");
    const off = page.getByTestId("drawer-tools-off");
    const row = off.locator("[data-tool=delete_message]");
    await row.getByTestId("tool-switch").click();
    // Nothing changed yet: an inline confirm, not a modal and not a success toast.
    await expect(row.getByTestId("tool-confirm")).toBeVisible();
    await expect(page.getByTestId("confirm-dialog")).toHaveCount(0);
    await expect(page.getByTestId("drawer-tools-on").locator("[data-tool=delete_message]")).toHaveCount(0);
    await row.getByTestId("tool-confirm-no").click();
    await expect(row.getByTestId("tool-confirm")).toHaveCount(0);
    await row.getByTestId("tool-switch").click();
    await row.getByTestId("tool-confirm-yes").click();
    await expect(page.getByTestId("drawer-tools-on").locator("[data-tool=delete_message]")).toBeVisible();
    const toast = page.getByTestId("toast").filter({ hasText: "delete_message turned on" });
    await expect(toast).toHaveAttribute("data-toast-type", "warning");
    await toast.getByTestId("toast-action").click();
    await expect(off.locator("[data-tool=delete_message]")).toBeVisible();
  });

  test("drawer: members can only turn org tools off for themselves", async ({ page }) => {
    await page.goto(`${SETTINGS}&admin=0`);
    await openDrawer(page, "Jira");
    await expect(page.getByTestId("drawer-tools-on-read-only")).toHaveCount(0);
    const offTool = page.getByTestId("drawer-tools-off").locator("[data-tool=create_issue]").getByTestId("tool-switch");
    await expect(offTool).toBeDisabled();
    await page.getByTestId("drawer-tools-on").locator("[data-tool=search_issues]").getByTestId("tool-switch").click();
    await expect(page.getByTestId("drawer-tools-off").locator("[data-tool=search_issues]")).toBeVisible();
  });

  test("drawer: Access, Activity, and Settings tabs; focus stays inside", async ({ page }) => {
    await page.goto(SETTINGS);
    await openDrawer(page, "GitHub");
    await expect(page.getByTestId("connector-drawer")).toContainText("Sandbox");
    await expect(page.getByTestId("connector-drawer-close")).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest("[data-testid=connector-drawer]")))).toBe(true);
    await page.getByTestId("connector-tab-access").click();
    await expect(page.getByTestId("drawer-access-sandbox")).toContainText("including any keys");
    await expect(page.getByTestId("drawer-access-sandbox-notes")).toContainText("tool permissions");
    const secret = page.getByTestId("secret-row").filter({ hasText: "GITHUB_PERSONAL_ACCESS_TOKEN" });
    await expect(secret).toContainText("Yours");
    await expect(secret).toContainText("saved");
    await secret.getByTestId("secret-replace").click();
    await secret.getByTestId("secret-input").fill("ghp_new");
    await secret.getByTestId("secret-save").click();
    await expect(page.getByText("GITHUB_PERSONAL_ACCESS_TOKEN saved · applies to new chats")).toBeVisible();
    await expect(secret.getByTestId("secret-input")).toHaveCount(0);
    await page.getByTestId("connector-tab-activity").click();
    await expect(page.getByTestId("drawer-activity-sandbox")).toBeVisible();
    await page.getByTestId("connector-tab-settings").click();
    await expect(page.getByTestId("drawer-settings-slug")).toContainText("mcp__github__");
    await expect(page.getByTestId("drawer-settings-target")).toHaveValue("npx -y @modelcontextprotocol/server-github");
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("connector-drawer")).toHaveCount(0);
  });

  test("drawer: org connector shows who is signed in, readable activity, and sign-everyone-out", async ({ page }) => {
    await page.goto(SETTINGS);
    await openDrawer(page, "Jira");
    await page.getByTestId("connector-tab-access").click();
    await expect(page.getByTestId("drawer-access-sign-in-state")).toContainText("Signed in");
    await expect(page.getByTestId("drawer-access-account")).toContainText("as eli@acme-analytics.com");
    await expect(page.getByTestId("drawer-access-signed-in-count")).toContainText("3 members are signed in.");
    await expect(page.getByTestId("drawer-access-sign-everyone-out")).toBeVisible();
    await page.getByTestId("drawer-access-sign-out").click();
    await expect(page.getByTestId("drawer-access-sign-in-state")).toHaveText("Needs sign-in");
    await page.getByTestId("drawer-access-sign-in").click();
    await expect(page.getByTestId("drawer-access-sign-in-state")).toContainText("Signed in");
    await page.getByTestId("connector-tab-activity").click();
    const table = page.getByTestId("drawer-activity-table");
    await expect(table.locator("tbody tr")).toHaveCount(5);
    await expect(table).toContainText("denied");
    await expect(table).toContainText("Tool is off for this connector");
    // "Who" is a person, never a Clerk id; the caller is marked.
    const who = table.getByTestId("activity-who");
    await expect(who.first()).toHaveText("eli@acme-analytics.com (you)");
    await expect(table).toContainText("priya@acme-analytics.com");
    expect(await table.innerText()).not.toMatch(/user_/);
  });

  test("remove an org connector names the object, the members, and the consequences", async ({ page }) => {
    await page.goto(SETTINGS);
    const row = page.getByTestId("connector-row").filter({ hasText: "Snowflake docs" });
    await row.getByTestId("connector-row-menu").click();
    await page.getByRole("menuitem", { name: "Remove…" }).click();
    const dialog = page.getByTestId("confirm-dialog");
    await expect(dialog).toContainText("Remove Snowflake docs for everyone?");
    await expect(dialog).toContainText("No one is signed in.");
    await expect(dialog).toContainText(/won't be stopped/);
    await page.getByRole("button", { name: "Remove connector" }).click();
    await expect(row).toHaveCount(0);
    await expect(page.getByText("Snowflake docs removed")).toBeVisible();
  });

  test("the org policy row expands and saves on the spot", async ({ page }) => {
    await page.goto(SETTINGS);
    await page.getByTestId("org-policy-toggle").click();
    await expect(page.getByTestId("org-policy-card")).toHaveAttribute("data-open", "true");
    const allow = page.getByTestId("org-policy-allow-personal");
    await allow.click();
    await expect(allow).toHaveAttribute("aria-checked", "false");
    await expect(page.getByText("Policy saved · applies to new chats")).toBeVisible();
    await expect(page.getByTestId("org-policy-summary")).toHaveText("Members can't add personal connectors");
    await allow.click();
    await page.getByTestId("org-policy-host-input").fill("*.atlassian.com");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Remove *.atlassian.com" })).toBeVisible();
    await expect(page.getByTestId("org-policy-summary")).toContainText("*.atlassian.com");
  });

  test("the sign-in callback opens the drawer on Access, toasts, and strips the params", async ({ page }) => {
    await page.goto(`${SETTINGS}&connector=con_jira&signin=ok`);
    await expect(page.getByTestId("connector-drawer")).toContainText("Jira");
    await expect(page.getByTestId("connector-tab-access")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText("Signed in to Jira · applies to new chats")).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.location.search)).toBe("?fixture=1");
    await page.keyboard.press("Escape");
    await page.goto(`${SETTINGS}&connector=con_jira&signin=error`);
    await expect(page.getByText(/refused sign-in to Jira/)).toBeVisible();
  });

  test("?open=<id> (from the chat panel) opens that connector's drawer", async ({ page }) => {
    await page.goto(`${SETTINGS}&open=con_slack`);
    await expect(page.getByTestId("connector-drawer")).toContainText("Slack");
    await expect(page.getByTestId("connector-tab-tools")).toHaveAttribute("aria-selected", "true");
    await expect.poll(() => page.evaluate(() => window.location.search)).toBe("?fixture=1");
  });

  test("narrow viewport: rows stay usable and the drawer is a full-screen sheet", async ({ page }) => {
    await page.setViewportSize({ width: 600, height: 900 });
    await page.goto(SETTINGS);
    const jira = page.getByTestId("connector-row").filter({ hasText: "Jira" });
    await expect(jira.getByTestId("connector-status-pill-compact")).toBeVisible();
    await expect(jira.getByTestId("connector-status-pill")).toBeHidden();
    const menu = jira.getByTestId("connector-row-menu");
    const box = await menu.boundingBox();
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
    await jira.getByTestId("connector-row-open").click();
    const drawer = page.getByTestId("connector-drawer");
    const drawerBox = await drawer.boundingBox();
    expect(Math.round(drawerBox?.width ?? 0)).toBe(600);
  });
});
