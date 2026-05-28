import { test, expect } from "@playwright/test";

test("direct URL to intro.py renders cells", async ({ page }) => {
  test.setTimeout(60_000);

  const errors: string[] = [];
  page.on("console", (m) => {
    const text = m.text().slice(0, 200);
    if (m.type() === "error") errors.push(text);
    // Log everything with "tab" or "file" or "session" for debugging
    if (/tab|file|session|activeTab|openFile|kernel|instantiate/i.test(text)) {
      console.log(`[notebook] ${text}`);
    }
  });

  // Log WebSocket activity
  page.on("websocket", (ws) => {
    console.log(`[WS] opened: ${ws.url().slice(0, 100)}`);
    ws.on("framereceived", (frame) => {
      const data = typeof frame.payload === "string" ? frame.payload.slice(0, 100) : "(binary)";
      console.log(`[WS] recv: ${data}`);
    });
    ws.on("close", () => console.log("[WS] closed"));
  });

  await page.goto(
    "http://localhost:3200/projects?project=0bf16b7b-4936-4f32-b1a6-d2234e8dab3d&branch=main&file=notebooks%2Fintro.py",
    { waitUntil: "domcontentloaded" }
  );

  await page.locator(".sp-root").waitFor({ timeout: 30_000 });
  // Wait for cells or 15 seconds
  for (let i = 0; i < 8; i++) {
    const cells = await page.locator(".cm-editor").count();
    if (cells >= 2) break;
    await page.waitForTimeout(2000);
    console.log(`  Waiting... ${cells} cells at ${(i+1)*2}s`);
  }

  // Check activeTab state
  const state = await page.evaluate(() => {
    const root = document.querySelector(".sp-root");
    return {
      hasCmEditor: document.querySelectorAll(".cm-editor").length,
      hasCmContent: document.querySelectorAll(".cm-content").length,
      hasRawEditor: document.querySelectorAll("textarea").length,
      spRootChildren: root?.children.length,
      bodyText: root?.textContent?.slice(0, 200),
      url: window.location.href,
      hasFileParam: new URL(window.location.href).searchParams.has("file"),
      // Check for "Select a file" or error states
      hasSelectFile: !!root?.querySelector('[class*="select"]'),
      hasError: !!root?.textContent?.match(/error|wrong|unauthorized/i),
    };
  });
  console.log("State:", JSON.stringify(state, null, 2));

  await page.screenshot({ path: "e2e-direct-url.png" });

  if (errors.length > 0) {
    console.log("Errors:", errors.filter(e => !e.includes("favicon") && !e.includes("JetBrains")).join("\n  "));
  }

  expect(state.hasCmEditor).toBeGreaterThanOrEqual(2);
});
