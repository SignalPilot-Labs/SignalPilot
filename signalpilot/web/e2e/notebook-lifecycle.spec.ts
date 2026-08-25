import { test, expect, type Page, type APIRequestContext } from "@playwright/test";

import { resolveProject } from "./helpers";

/**
 * The canonical end-to-end user journey on Runtime v2:
 *
 *   create project → open it → create a notebook → write print("hello world")
 *   → run the cell on the live kernel → see the output → verify the file is a
 *   durable revision in the workspace store → reload and see it again.
 *
 * Everything runs against the real local stack (gateway + notebook runtime +
 * S3 workspace store). No mocks.
 */

const GATEWAY = "http://localhost:3300";

async function getApiKey(request: APIRequestContext): Promise<string> {
  const resp = await request.get("http://localhost:3200/api/local-key");
  return ((await resp.json()) as { key?: string }).key ?? "";
}

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(`PAGE: ${err.message.slice(0, 300)}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`CONSOLE: ${msg.text().slice(0, 300)}`);
  });
  return errors;
}

test.describe.serial("Notebook lifecycle (hello world)", () => {
  let apiKey = "";
  let projectId = "";
  const notebookName = "hello_e2e";

  test.beforeAll(async ({ request }) => {
    apiKey = await getApiKey(request);
    // Direct mode binds the runtime to ONE project's workspace store
    // (SP_PROJECT_ID) — sessions for other projects are refused
    // (SP_PROJECT_MISMATCH), so this journey runs in the pinned project.
    // Vercel mode launches a per-project sandbox and has no such pin.
    projectId = (await resolveProject(request)).id;
    // Clean slate: earlier suites leave kernel sessions (and their save
    // dialogs / concurrent editors) behind, which races the __new__ boot.
    await request.delete(`${GATEWAY}/api/notebook-sessions`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    }).catch(() => {});
    await new Promise((r) => setTimeout(r, 3000));
  });

  test.afterAll(async ({ request }) => {
    // Leave the shared fixture project as we found it.
    if (!projectId) return;
    const head = await request.get(
      `${GATEWAY}/api/workspace-projects/${projectId}/revisions?branch=main&limit=1`,
      { headers: { Authorization: `Bearer ${apiKey}` } },
    );
    const revs = ((await head.json()) as { revisions?: Array<{ revision: number }> }).revisions ?? [];
    await request.post(`${GATEWAY}/api/workspace-projects/${projectId}/files:batch`, {
      headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
      data: {
        branch: "main",
        base_revision: revs[0]?.revision ?? null,
        deletes: [`${notebookName}.py`, `__sp__/session/${notebookName}.py.json`],
        message: "e2e: remove lifecycle fixture notebook",
      },
    }).catch(() => {});
  });

  test("create notebook, run print('hello world'), see output", async ({ page }) => {
    test.setTimeout(180_000);
    const errors = collectErrors(page);

    // ── Open the brand-new (empty) project ─────────────────────────
    await page.goto(
      `/projects?project=${projectId}&branch=main&file=__new__notebook`,
      { waitUntil: "domcontentloaded" },
    );
    await page.locator(".sp-root").waitFor({ timeout: 90_000 });
    await page.locator(".cm-editor").first().waitFor({ timeout: 60_000 });
    await page.waitForTimeout(1500);

    // ── Write the script ───────────────────────────────────────────
    const cm = page.locator(".cm-editor").first().locator(".cm-content");
    await cm.click();
    await page.keyboard.type('print("hello world")', { delay: 20 });
    await page.waitForTimeout(500);
    expect(await cm.textContent()).toContain('print("hello world")');

    // ── Run it (Ctrl+Enter = run cell) ─────────────────────────────
    await page.keyboard.press("Control+Enter");

    // The kernel executes and the console output area shows the print.
    const output = page.locator("[data-testid=console-output-area]");
    await expect(output.first()).toContainText("hello world", { timeout: 60_000 });

    // ── Save so it becomes a durable revision ──────────────────────
    // A __new__ notebook has no name yet: Ctrl+S opens the Save dialog.
    await page.keyboard.press("Control+s");
    const dialog = page.getByText("Save notebook");
    await dialog.waitFor({ timeout: 10_000 });
    const nameInput = page.locator("dialog input, [role=dialog] input").first();
    await nameInput.fill(`${notebookName}.py`);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(3000);

    const fatal = errors.filter((e) => e.includes("TypeError") || e.includes("500 "));
    expect(fatal, `no fatal errors: ${fatal.join(" | ")}`).toHaveLength(0);
  });

  test("the notebook is a durable revision in the workspace store", async ({ request }) => {
    const list = await request.post(
      `${GATEWAY}/api/workspace-projects/${projectId}/files:list`,
      {
        headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
        data: { branch: "main" },
      },
    );
    expect(list.ok(), `files:list ${list.status()}`).toBe(true);
    const files = ((await list.json()) as { files?: Array<{ path: string }> }).files ?? [];
    const notebooks = files.filter((f) => f.path.includes("hello_e2e"));
    expect(notebooks.length, `expected a saved .py notebook, got: ${files.map((f) => f.path).join(", ")}`).toBeGreaterThan(0);
  });

  test("reload replays the notebook with its content", async ({ page, request }) => {
    test.setTimeout(120_000);
    // Find the saved notebook path from the store, then deep-link to it.
    const list = await request.post(
      `${GATEWAY}/api/workspace-projects/${projectId}/files:list`,
      {
        headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
        data: { branch: "main" },
      },
    );
    const files = ((await list.json()) as { files?: Array<{ path: string }> }).files ?? [];
    const nb = files.find((f) => f.path.includes("hello_e2e") && f.path.endsWith(".py"));
    expect(nb, "saved notebook must exist").toBeTruthy();

    const errors = collectErrors(page);
    await page.goto(
      `/projects?project=${projectId}&branch=main&file=${encodeURIComponent(nb!.path)}`,
      { waitUntil: "domcontentloaded" },
    );
    await page.locator(".sp-root").waitFor({ timeout: 90_000 });
    await page.locator(".cm-editor").first().waitFor({ timeout: 60_000 });
    await page.waitForTimeout(2000);

    const text = await page.locator(".sp-root").innerText();
    expect(text).toContain("hello world");
    const fatal = errors.filter((e) => e.includes("TypeError"));
    expect(fatal, fatal.join(" | ")).toHaveLength(0);
  });
});
