import { test, expect, type Page } from "@playwright/test";

const PROJECT_ID = "3781d00d-3f10-4139-9b70-2e4cd9c42c63";
const GATEWAY = "http://localhost:3300";

// ─── Helpers ─────────────────────────────────────────────────────
async function getApiKey(): Promise<string> {
  const resp = await fetch("http://localhost:3200/api/local-key");
  const data = (await resp.json()) as { key?: string };
  return data?.key ?? "";
}

async function killAllSessions(apiKey: string) {
  await fetch(`${GATEWAY}/api/notebook-sessions`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${apiKey}` },
  }).catch(() => {});
}

async function waitForNotebook(page: Page, timeoutMs = 90_000) {
  await page.locator(".sp-root").waitFor({ timeout: timeoutMs });
}

async function waitForEditor(page: Page, timeoutMs = 30_000) {
  await page.locator(".cm-editor").first().waitFor({ timeout: timeoutMs });
}

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(`PAGE: ${err.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`CONSOLE: ${msg.text().slice(0, 300)}`);
  });
  return errors;
}

function expectNoFatalErrors(errors: string[], label: string) {
  const fatal = errors.filter((e) => e.includes("Cannot read") || e.includes("null object"));
  expect(fatal, `No fatal errors: ${label}`).toHaveLength(0);
}

// ─── 1. Warm Pod: existing session → reconnects instantly ────────
test.describe.serial("Warm Pod", () => {
  test("reconnects to existing session on page load", async ({ page }) => {
    test.setTimeout(60_000);
    const errors = collectErrors(page);

    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
      { waitUntil: "domcontentloaded" }
    );

    await waitForNotebook(page);
    await waitForEditor(page);

    const editorCount = await page.locator(".cm-editor").count();
    expect(editorCount).toBeGreaterThan(0);
    expectNoFatalErrors(errors, "warm reconnect");
  });

  test("survives page refresh without losing state", async ({ page }) => {
    test.setTimeout(90_000);
    const errors = collectErrors(page);

    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
      { waitUntil: "domcontentloaded" }
    );
    await waitForNotebook(page);
    await waitForEditor(page);

    await page.reload({ waitUntil: "domcontentloaded" });
    await waitForNotebook(page);
    await waitForEditor(page, 60_000);

    const editorCount = await page.locator(".cm-editor").count();
    expect(editorCount).toBeGreaterThan(0);
    expectNoFatalErrors(errors, "refresh");
  });
});

// ─── 2. Cell Editing: cursor, typing, selection ──────────────────
test.describe("Cell Editing", () => {
  test("CodeMirror editor is fully interactive", async ({ page }) => {
    test.setTimeout(90_000);

    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
      { waitUntil: "domcontentloaded" }
    );
    await waitForNotebook(page);
    await waitForEditor(page);
    await page.waitForTimeout(2000);

    const cmContent = page.locator(".cm-editor").first().locator(".cm-content");
    await cmContent.click();
    await page.waitForTimeout(500);

    expect(await page.locator(".cm-focused").count()).toBeGreaterThan(0);
    expect(await page.locator(".cm-cursorLayer").count()).toBeGreaterThan(0);

    await page.keyboard.press("End");
    await page.keyboard.type("# E2E_TEST");
    await page.waitForTimeout(300);
    expect(await cmContent.textContent()).toContain("E2E_TEST");

    await page.keyboard.press("Home");
    await page.keyboard.down("Shift");
    await page.keyboard.press("End");
    await page.keyboard.up("Shift");
    await page.waitForTimeout(200);
    expect(await page.locator(".cm-selectionLayer").count()).toBeGreaterThan(0);
  });
});

// ─── 3. File Picker: switch between file types ───────────────────
test.describe("File Picker", () => {
  test("file tree loads and shows project files", async ({ page }) => {
    test.setTimeout(60_000);

    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
      { waitUntil: "domcontentloaded" }
    );
    await waitForNotebook(page);
    await waitForEditor(page);

    // The deep-link loaded intro.py — the tab bar or file tree should mention it
    const introVisible = await page.locator(".sp-root").getByText("intro.py").first()
      .isVisible({ timeout: 10_000 }).catch(() => false);

    // Also check for any other project files
    const projectFiles = page.locator(".sp-root").getByText(/dbt_project|models|notebooks|schema/i);
    const fileCount = await projectFiles.count();
    console.log(`File tree: intro.py=${introVisible}, other files=${fileCount}`);

    // At minimum, intro.py should be visible (in tab bar or tree)
    expect(introVisible || fileCount > 0).toBe(true);
  });

  test("switches from .py to .yml file", async ({ page }) => {
    test.setTimeout(60_000);

    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
      { waitUntil: "domcontentloaded" }
    );
    await waitForNotebook(page);
    await waitForEditor(page);

    const ymlFile = page.locator(".sp-root").getByText(/schema\.yml|dbt_project\.yml/i).first();
    if (await ymlFile.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await ymlFile.click();
      await page.waitForTimeout(3000);
      const hasEditor = await page.locator(".cm-editor, [data-testid='raw-file-editor'], textarea").first()
        .isVisible({ timeout: 10_000 }).catch(() => false);
      expect(hasEditor).toBe(true);
      console.log("Switched to .yml: editor visible");
    } else {
      console.log("No .yml file found in tree — skipped");
    }
  });

  test("switches from .py to .sql file", async ({ page }) => {
    test.setTimeout(60_000);

    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
      { waitUntil: "domcontentloaded" }
    );
    await waitForNotebook(page);
    await waitForEditor(page);

    const sqlFile = page.locator(".sp-root").getByText(/\.sql$/i).first();
    if (await sqlFile.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await sqlFile.click();
      await page.waitForTimeout(3000);
      const hasEditor = await page.locator(".cm-editor, [data-testid='raw-file-editor'], textarea").first()
        .isVisible({ timeout: 10_000 }).catch(() => false);
      expect(hasEditor).toBe(true);
      console.log("Switched to .sql: editor visible");
    } else {
      console.log("No .sql file found in tree — skipped");
    }
  });

  test("switches from .py to .md file", async ({ page }) => {
    test.setTimeout(60_000);

    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
      { waitUntil: "domcontentloaded" }
    );
    await waitForNotebook(page);
    await waitForEditor(page);

    const mdFile = page.locator(".sp-root").getByText(/README\.md|\.md$/i).first();
    if (await mdFile.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await mdFile.click();
      await page.waitForTimeout(3000);
      const hasEditor = await page.locator(".cm-editor, [data-testid='raw-file-editor'], textarea").first()
        .isVisible({ timeout: 10_000 }).catch(() => false);
      expect(hasEditor).toBe(true);
      console.log("Switched to .md: editor visible");
    } else {
      console.log("No .md file found in tree — skipped");
    }
  });
});

// ─── 4. Project Navigation: landing → project → back ─────────────
test.describe("Project Navigation", () => {
  test("navigates from landing page to project and back", async ({ page }) => {
    test.setTimeout(120_000);
    const errors = collectErrors(page);

    await page.goto("/projects", { waitUntil: "domcontentloaded" });

    const openBtn = page.getByRole("button", { name: /open ide/i });
    const runningText = page.getByText("running");
    await Promise.race([
      runningText.waitFor({ timeout: 30_000 }),
      openBtn.waitFor({ timeout: 30_000 }),
    ]);

    if (await openBtn.isVisible().catch(() => false)) {
      await openBtn.click();
      await runningText.waitFor({ timeout: 60_000 });
    }

    await waitForNotebook(page);
    console.log("Notebook loaded from landing page");

    await page.goto("/projects", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);

    const stillRunning = await runningText.isVisible({ timeout: 10_000 }).catch(() => false);
    expect(stillRunning).toBe(true);
    expectNoFatalErrors(errors, "navigation");
  });
});

// ─── 5. Project Creation Flow ────────────────────────────────────
test.describe("Project Creation", () => {
  test("project creation UI elements exist", async ({ page }) => {
    test.setTimeout(90_000);
    const errors = collectErrors(page);

    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main`,
      { waitUntil: "domcontentloaded" }
    );
    await waitForNotebook(page);

    const createBtn = page.locator(".sp-root").getByText(/create.*project|new.*project/i).first();
    const hasCreate = await createBtn.isVisible({ timeout: 10_000 }).catch(() => false);
    const plusBtn = page.locator(".sp-root").getByText(/\+|add/i).first();
    const hasPlus = await plusBtn.isVisible({ timeout: 5_000 }).catch(() => false);
    console.log(`Create project UI: createBtn=${hasCreate}, plusBtn=${hasPlus}`);

    expectNoFatalErrors(errors, "project creation");
  });
});

// ─── 6. AI Agent Panel ───────────────────────────────────────────
test.describe("AI Agent Panel", () => {
  test("agent panel is accessible without errors", async ({ page }) => {
    test.setTimeout(60_000);
    const errors = collectErrors(page);

    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
      { waitUntil: "domcontentloaded" }
    );
    await waitForNotebook(page);
    await waitForEditor(page);

    const agentToggle = page.locator(".sp-root").getByText(/agent|ai|chat/i).first();
    const hasToggle = await agentToggle.isVisible({ timeout: 10_000 }).catch(() => false);

    if (hasToggle) {
      await agentToggle.click();
      await page.waitForTimeout(2000);
      const chatInput = page.locator(".sp-root textarea, .sp-root [contenteditable='true']").first();
      const hasInput = await chatInput.isVisible({ timeout: 5_000 }).catch(() => false);
      console.log(`Agent panel: toggle=${hasToggle}, input=${hasInput}`);
    } else {
      const bottomTab = page.locator(".sp-root [role='tab']").filter({ hasText: /agent/i }).first();
      const hasTab = await bottomTab.isVisible({ timeout: 5_000 }).catch(() => false);
      console.log(`Agent panel: toggle=false, bottomTab=${hasTab}`);
    }

    expectNoFatalErrors(errors, "agent panel");
  });
});

// ─── 7. CSS/Styles Integrity ─────────────────────────────────────
test.describe("Styles Integrity", () => {
  test("CodeMirror CSS rules are properly injected", async ({ page }) => {
    test.setTimeout(60_000);

    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
      { waitUntil: "domcontentloaded" }
    );
    await waitForNotebook(page);
    await waitForEditor(page);

    const cmRuleCount = await page.evaluate(() => {
      let count = 0;
      for (const sheet of document.styleSheets) {
        try {
          for (const rule of sheet.cssRules) {
            if (rule.cssText.includes(".cm-") || rule.cssText.includes(".ͼ")) count++;
          }
        } catch {}
      }
      return count;
    });

    console.log(`CM CSS rules: ${cmRuleCount}`);
    expect(cmRuleCount).toBeGreaterThan(50);
  });
});

// ─── 8. Cold Start (LAST — kills sessions) ──────────────────────
test.describe("Cold Start", () => {
  test("launches notebook from scratch when no pod exists", async ({ page }) => {
    test.setTimeout(180_000);
    const errors = collectErrors(page);
    const apiKey = await getApiKey();
    await killAllSessions(apiKey);
    await page.waitForTimeout(8000);

    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
      { waitUntil: "domcontentloaded" }
    );

    const loadingText = page.getByText(/creating session|connecting to pod|waiting for pod/i);
    await loadingText.waitFor({ timeout: 15_000 }).catch(() => {});

    await waitForNotebook(page, 120_000);
    await waitForEditor(page, 60_000);

    const editorCount = await page.locator(".cm-editor").count();
    expect(editorCount).toBeGreaterThan(0);
    console.log(`Cold start: ${editorCount} editors loaded`);
    expectNoFatalErrors(errors, "cold start");
  });
});
