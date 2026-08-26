import { expect, test, type Page } from "@playwright/test";

/**
 * Staging/local fixture contract:
 *
 * SP_E2E_SHARE_PROJECT_ID identifies an authenticated caller-visible project.
 * Its branch must contain the four text files below. Paths and source markers
 * may be overridden with the matching SP_E2E_SHARE_* environment variables.
 * Cloud CI supplies user A/B in one org and user C in another; the gateway
 * authorization matrix remains covered locally when those Clerk states are
 * unavailable.
 */
const fixture = {
  project: process.env.SP_E2E_SHARE_PROJECT_ID ?? "",
  branch: process.env.SP_E2E_SHARE_BRANCH ?? "main",
  notebook: process.env.SP_E2E_SHARE_NOTEBOOK ?? "notebooks/shareability.py",
  module: process.env.SP_E2E_SHARE_MODULE ?? "src/shareability_module.py",
  invalid: process.env.SP_E2E_SHARE_INVALID ?? "src/invalid_shareability.py",
  sql: process.env.SP_E2E_SHARE_SQL ?? "models/shareability.sql",
  notebookMarker: process.env.SP_E2E_SHARE_NOTEBOOK_MARKER ?? "SHARE_NOTEBOOK_CELL",
  moduleMarker: process.env.SP_E2E_SHARE_MODULE_MARKER ?? "RAW_MODULE_SENTINEL",
  invalidMarker: process.env.SP_E2E_SHARE_INVALID_MARKER ?? "INVALID_PY_SENTINEL",
  sqlMarker: process.env.SP_E2E_SHARE_SQL_MARKER ?? "SQL_SENTINEL",
};

function editorHref(pathname: "/projects" | "/notebook", file: string): string {
  const params = new URLSearchParams({
    project: fixture.project,
    branch: fixture.branch,
    file,
  });
  return `${pathname}?${params.toString()}`;
}

async function waitForRuntime(page: Page): Promise<void> {
  await page.locator(".sp-root").waitFor({ timeout: 120_000 });
  await page.getByText("running", { exact: true }).waitFor({ timeout: 120_000 });
}

async function clickTreeFile(page: Page, file: string): Promise<void> {
  const parts = file.split("/");
  const fileNode = page
    .locator(".sp-root")
    .getByText(parts.at(-1)!, { exact: true })
    .first();
  for (const folder of parts.slice(0, -1)) {
    if (await fileNode.isVisible().catch(() => false)) {
      break;
    }
    const folderNode = page.locator(".sp-root").getByText(folder, { exact: true }).first();
    if (await folderNode.isVisible().catch(() => false)) {
      await folderNode.click();
    }
  }
  await fileNode.click();
}

async function readShareLink(page: Page): Promise<string> {
  await page.getByRole("button", { name: /share/i }).click();
  return page.evaluate(() => navigator.clipboard.readText());
}

test.describe.serial("authenticated notebook shareability", () => {
  test.skip(
    !fixture.project,
    "Set SP_E2E_SHARE_PROJECT_ID and provision the documented four-file fixture",
  );

  test("switches semantic file kinds in place on the /projects surface", async ({
    context,
    page,
  }) => {
    test.setTimeout(180_000);
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);

    let documentRequests = 0;
    let healthRequests = 0;
    let syncRequests = 0;
    let sessionRequests = 0;
    let webSockets = 0;
    page.on("request", (request) => {
      if (request.resourceType() === "document") documentRequests += 1;
      const url = request.url();
      if (/\/notebook\/[^/]+\/health(?:\?|$)/.test(url)) healthRequests += 1;
      if (url.includes("/api/notebook/static")) syncRequests += 1;
      if (url.includes("/api/notebook-sessions")) sessionRequests += 1;
    });
    page.on("websocket", () => {
      webSockets += 1;
    });

    await page.addInitScript(({ module }) => {
      localStorage.setItem(
        "sp:open-tabs",
        JSON.stringify([
          {
            id: "stale-extension-tab",
            path: module,
            type: "notebook",
            sessionId: "s_stale",
            name: module.split("/").at(-1),
          },
        ]),
      );
      localStorage.setItem("sp:active-tab-id", JSON.stringify("stale-extension-tab"));
    }, { module: fixture.module });

    await page.goto(editorHref("/projects", fixture.notebook), {
      waitUntil: "domcontentloaded",
    });
    await waitForRuntime(page);

    await expect(page.getByLabel("Platform navigation")).toBeVisible();
    await expect(page.locator(".sp-root")).toContainText(fixture.notebookMarker);
    await expect(page.getByTestId("raw-file-editor")).toHaveCount(0);

    await page.reload({ waitUntil: "domcontentloaded" });
    await waitForRuntime(page);
    await expect(page.getByLabel("Platform navigation")).toBeVisible();
    await expect(page.locator(".sp-root")).toContainText(fixture.notebookMarker);
    await expect(page.getByTestId("raw-file-editor")).toHaveCount(0);

    const bootCounts = {
      documents: documentRequests,
      health: healthRequests,
      sync: syncRequests,
      sessions: sessionRequests,
      webSockets,
    };
    await page.evaluate(() => {
      (window as Window & { __shareabilityRoot?: Element | null }).__shareabilityRoot =
        document.querySelector(".sp-root");
    });

    await clickTreeFile(page, fixture.module);
    await expect(page).toHaveURL(new RegExp(`file=${encodeURIComponent(fixture.module)}`));
    await expect(page.getByTestId("raw-file-editor")).toContainText(fixture.moduleMarker);
    expect(documentRequests).toBe(bootCounts.documents);
    expect(healthRequests).toBe(bootCounts.health);
    expect(syncRequests).toBe(bootCounts.sync);
    expect(sessionRequests).toBe(bootCounts.sessions);
    expect(webSockets).toBe(bootCounts.webSockets);

    await clickTreeFile(page, fixture.invalid);
    await expect(page.getByTestId("raw-file-editor")).toContainText(fixture.invalidMarker);

    await clickTreeFile(page, fixture.sql);
    await expect(page.getByTestId("raw-file-editor")).toContainText(fixture.sqlMarker);

    await page.goBack();
    await expect(page.getByTestId("raw-file-editor")).toContainText(fixture.invalidMarker);
    await page.goForward();
    await expect(page.getByTestId("raw-file-editor")).toContainText(fixture.sqlMarker);

    const sameRoot = await page.evaluate(() => {
      const win = window as Window & { __shareabilityRoot?: Element | null };
      return win.__shareabilityRoot === document.querySelector(".sp-root");
    });
    expect(sameRoot).toBe(true);

    await clickTreeFile(page, fixture.notebook);
    await expect(page.locator(".sp-root")).toContainText(fixture.notebookMarker);
    await expect(page.getByTestId("raw-file-editor")).toHaveCount(0);
    expect(documentRequests).toBe(bootCounts.documents);
    expect(healthRequests).toBe(bootCounts.health);
    expect(syncRequests).toBe(bootCounts.sync);
    expect(sessionRequests).toBe(bootCounts.sessions);
    expect(webSockets).toBe(bootCounts.webSockets + 1);
  });

  test("Share canonicalizes both editor surfaces to the same /projects URL", async ({
    context,
    page,
  }) => {
    test.setTimeout(180_000);
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);

    await page.goto(editorHref("/projects", fixture.notebook), {
      waitUntil: "domcontentloaded",
    });
    await waitForRuntime(page);
    await expect(page.getByRole("link", { name: /full screen/i })).toHaveAttribute(
      "href",
      editorHref("/notebook", fixture.notebook),
    );
    const projectsShare = await readShareLink(page);

    await page.goto(editorHref("/notebook", fixture.notebook), {
      waitUntil: "domcontentloaded",
    });
    await waitForRuntime(page);
    await expect(page.getByLabel("Platform navigation")).toHaveCount(0);
    const popoutShare = await readShareLink(page);

    expect(popoutShare).toBe(projectsShare);
    const shared = new URL(projectsShare);
    expect(shared.pathname).toBe("/projects");
    expect(shared.searchParams.get("project")).toBe(fixture.project);
    expect(shared.searchParams.get("branch")).toBe(fixture.branch);
    expect(shared.searchParams.get("file")).toBe(fixture.notebook);
    expect(shared.searchParams.has("session_id")).toBe(false);
    expect(shared.toString()).not.toMatch(/\/notebook\/[^/?]+/);
  });
});
