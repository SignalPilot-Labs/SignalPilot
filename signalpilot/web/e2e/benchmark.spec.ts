import { test } from "@playwright/test";

const PROJECT_ID = "3781d00d-3f10-4139-9b70-2e4cd9c42c63";
const GATEWAY = "http://localhost:3300";

interface BenchmarkResult {
  name: string;
  ms: number;
  status: "pass" | "fail";
  detail?: string;
}

const results: BenchmarkResult[] = [];

function record(name: string, ms: number, status: "pass" | "fail" = "pass", detail?: string) {
  results.push({ name, ms, status, detail });
}

async function timed<T>(name: string, fn: () => Promise<T>): Promise<T | null> {
  const t0 = performance.now();
  try {
    const result = await fn();
    record(name, Math.round(performance.now() - t0), "pass");
    return result;
  } catch (e) {
    record(name, Math.round(performance.now() - t0), "fail", String(e).slice(0, 80));
    return null;
  }
}

async function getApiKey(): Promise<string> {
  const resp = await fetch("http://localhost:3200/api/local-key");
  const data = (await resp.json()) as { key?: string };
  return data?.key ?? "";
}

test("Notebook Performance Benchmark", async ({ page }) => {
  test.setTimeout(600_000);

  // ─── WARM POD BENCHMARKS ───────────────────────────────────────
  await timed("1. Warm pod → .sp-root visible", async () => {
    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
      { waitUntil: "domcontentloaded" }
    );
    await page.locator(".sp-root").waitFor({ timeout: 60_000 });
  });

  await timed("2. Warm pod → first cm-editor", async () => {
    await page.locator(".cm-editor").first().waitFor({ timeout: 30_000 });
  });

  await timed("3. Warm pod → all cells rendered", async () => {
    await page.waitForTimeout(500);
    const count = await page.locator(".cm-editor").count();
    if (count < 2) throw new Error(`Only ${count} cells`);
  });

  // ─── CELL INTERACTION ──────────────────────────────────────────
  await timed("4. Click cell → .cm-focused", async () => {
    await page.locator(".cm-editor").first().locator(".cm-content").click();
    await page.locator(".cm-focused").first().waitFor({ timeout: 5_000 });
  });

  await timed("5. Type 20 chars → visible", async () => {
    await page.keyboard.type("benchmark_test_input");
    await page.waitForTimeout(100);
    const text = await page.locator(".cm-editor").first().locator(".cm-content").textContent();
    if (!text?.includes("benchmark_test_input")) throw new Error("Text not found");
  });

  // ─── IN-APP FILE SWITCH (no page.goto) ─────────────────────────
  // Open the file panel and switch files within the notebook
  await timed("6. Open file panel sidebar", async () => {
    // Wait for file panel to be clickable
    await page.waitForTimeout(1000);
    // The sidebar icons strip — click the first icon (Files)
    const icons = page.locator(".sp-root div[class*='flex'][class*='flex-col'][class*='items-start']").first();
    const firstIcon = icons.locator("div[class*='rounded']").first();
    if (await firstIcon.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await firstIcon.click();
    }
    // Wait for tree to load
    let loaded = false;
    for (let i = 0; i < 10; i++) {
      await page.waitForTimeout(1000);
      const entries = await page.locator(".sp-root [role='treeitem']").count();
      if (entries > 0) { loaded = true; break; }
    }
    if (!loaded) throw new Error("File tree never loaded");
  });

  await timed("7. In-app: click dbt_project.yml", async () => {
    const ymlNode = page.locator(".sp-root [role='treeitem']").filter({ hasText: "dbt_project.yml" }).first();
    await ymlNode.waitFor({ timeout: 5_000 });
    await ymlNode.click();
    // Wait for content to change — look for raw editor or different CM content
    await page.waitForTimeout(500);
    await page.locator(".cm-editor, textarea").first().waitFor({ timeout: 10_000 });
  });

  await timed("8. In-app: yml content visible", async () => {
    // Verify the content is actually yml
    const content = await page.locator(".cm-editor .cm-content, textarea").first().textContent();
    if (!content?.includes("name:") && !content?.includes("version:")) throw new Error("YML content not found");
  });

  await timed("9. In-app: click notebooks folder", async () => {
    const notebooks = page.locator(".sp-root [role='treeitem']").filter({ hasText: "notebooks" }).first();
    if (await notebooks.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await notebooks.click();
      await page.waitForTimeout(500);
    }
  });

  await timed("10. In-app: click intro.py", async () => {
    const introNode = page.locator(".sp-root [role='treeitem']").filter({ hasText: "intro.py" }).first();
    await introNode.waitFor({ timeout: 5_000 });
    await introNode.click();
    await page.locator(".cm-editor").first().waitFor({ timeout: 10_000 });
  });

  await timed("11. In-app: .py cells rendered", async () => {
    await page.waitForTimeout(500);
    const count = await page.locator(".cm-editor").count();
    if (count < 2) throw new Error(`Only ${count} cells`);
  });

  await timed("12. In-app: click profiles.yml", async () => {
    const profilesNode = page.locator(".sp-root [role='treeitem']").filter({ hasText: "profiles.yml" }).first();
    if (await profilesNode.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await profilesNode.click();
      await page.locator(".cm-editor, textarea").first().waitFor({ timeout: 10_000 });
    }
  });

  await timed("13. In-app: back to intro.py", async () => {
    const introNode = page.locator(".sp-root [role='treeitem']").filter({ hasText: "intro.py" }).first();
    if (await introNode.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await introNode.click();
      await page.locator(".cm-editor").first().waitFor({ timeout: 10_000 });
      await page.waitForTimeout(500);
      const count = await page.locator(".cm-editor").count();
      if (count < 2) throw new Error(`Only ${count} cells`);
    }
  });

  // ─── FULL PAGE NAVIGATION (for comparison) ─────────────────────
  await timed("14. Full nav: goto .yml page", async () => {
    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main&file=dbt_project.yml`,
      { waitUntil: "domcontentloaded" }
    );
    await page.locator(".sp-root").waitFor({ timeout: 60_000 });
    await page.locator(".cm-editor, textarea").first().waitFor({ timeout: 30_000 });
  });

  await timed("15. Full nav: goto .py page", async () => {
    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
      { waitUntil: "domcontentloaded" }
    );
    await page.locator(".sp-root").waitFor({ timeout: 60_000 });
    await page.locator(".cm-editor").first().waitFor({ timeout: 30_000 });
  });

  // ─── PAGE REFRESH ──────────────────────────────────────────────
  await timed("16. Refresh → .sp-root visible", async () => {
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.locator(".sp-root").waitFor({ timeout: 60_000 });
  });

  await timed("17. Refresh → cm-editor visible", async () => {
    await page.locator(".cm-editor").first().waitFor({ timeout: 30_000 });
  });

  // ─── API LATENCY ──────────────────────────────────────────────
  await timed("18. Gateway /health", async () => {
    const r = await fetch(`${GATEWAY}/health`);
    if (!r.ok) throw new Error(`${r.status}`);
  });

  await timed("19. Web /api/local-key", async () => {
    const r = await fetch("http://localhost:3200/api/local-key");
    if (!r.ok) throw new Error(`${r.status}`);
  });

  const apiKey = await getApiKey();
  await timed("20. Pod /health via proxy", async () => {
    const sessResp = await fetch(`${GATEWAY}/api/notebook-sessions`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    const sess = (await sessResp.json()) as { id?: string; notebook_url?: string };
    if (!sess?.id) throw new Error("No session");
    const tokenMatch = sess.notebook_url?.match(/[?&]token=([^&]+)/);
    const token = tokenMatch?.[1] ?? apiKey;
    const r = await fetch(`${GATEWAY}/notebook/${sess.id}/health`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!r.ok) throw new Error(`${r.status}`);
  });

  // ─── CSS CHECK ─────────────────────────────────────────────────
  await timed("21. CM CSS rules count", async () => {
    const count = await page.evaluate(() => {
      let n = 0;
      for (const s of document.styleSheets) {
        try { for (const r of s.cssRules) if (r.cssText.includes(".cm-")) n++; } catch {}
      }
      return n;
    });
    if (count < 50) throw new Error(`Only ${count}`);
    record("    (CM rules)", 0, "pass", `${count}`);
  });

  // ─── COLD START ────────────────────────────────────────────────
  await timed("22. Cold start: kill session", async () => {
    await fetch(`${GATEWAY}/api/notebook-sessions`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    await new Promise((r) => setTimeout(r, 5000));
  });

  await timed("23. Cold start → .sp-root", async () => {
    await page.goto(
      `/projects?project=${PROJECT_ID}&branch=main&file=notebooks%2Fintro.py`,
      { waitUntil: "domcontentloaded" }
    );
    await page.locator(".sp-root").waitFor({ timeout: 120_000 });
  });

  await timed("24. Cold start → cm-editor", async () => {
    await page.locator(".cm-editor").first().waitFor({ timeout: 60_000 });
  });

  // ─── PRINT TABLE ──────────────────────────────────────────────
  const nameW = Math.max(...results.map((r) => r.name.length), 10);

  console.log("");
  console.log("┌" + "─".repeat(nameW + 2) + "┬──────────┬────────┬──────────────────────────────────┐");
  console.log("│ " + "Benchmark".padEnd(nameW) + " │     Time │ Status │ Detail                           │");
  console.log("├" + "─".repeat(nameW + 2) + "┼──────────┼────────┼──────────────────────────────────┤");

  let totalMs = 0;
  let passed = 0;
  let failed = 0;

  for (const r of results) {
    if (r.name.startsWith("    (")) continue;
    const s = r.status === "pass" ? " PASS " : " FAIL ";
    const d = (r.detail ?? "").slice(0, 32);
    const t = r.ms > 0 ? `${r.ms}ms` : "";
    console.log("│ " + r.name.padEnd(nameW) + " │ " + t.padStart(8) + " │" + s + "│ " + d.padEnd(32) + " │");
    totalMs += r.ms;
    if (r.status === "pass") passed++;
    else failed++;
  }

  console.log("├" + "─".repeat(nameW + 2) + "┼──────────┼────────┼──────────────────────────────────┤");
  console.log("│ " + "TOTAL".padEnd(nameW) + " │ " + `${totalMs}ms`.padStart(8) + " │ " + `${passed}/${passed + failed}`.padEnd(5) + " │ " + `${passed} passed, ${failed} failed`.padEnd(32) + " │");
  console.log("└" + "─".repeat(nameW + 2) + "┴──────────┴────────┴──────────────────────────────────┘");

  const details = results.filter((r) => r.name.startsWith("    ("));
  if (details.length > 0) {
    for (const d of details) console.log(`  ${d.name}: ${d.detail}`);
  }
});
