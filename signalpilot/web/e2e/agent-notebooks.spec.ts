import { test, expect } from "@playwright/test";

/**
 * Agent notebooks: the Notebooks page lists agent-generated analyses, and
 * opening one replays the chart/table/interactive outputs from the committed
 * session snapshot.
 */

test("Notebooks page lists agent notebooks and opens with outputs", async ({ page }) => {
  test.setTimeout(120_000);

  await page.goto("/notebooks", { waitUntil: "domcontentloaded" });
  // Listed entry from the MCP run
  const entry = page.getByText("deep_analysis_demo.py").first();
  await expect(entry).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("outputs").first()).toBeVisible();

  // Open it — standard editor with replayed outputs
  await entry.click();
  await page.locator(".sp-root").waitFor({ timeout: 90_000 });
  await page.locator(".cm-editor").first().waitFor({ timeout: 60_000 });
  await page.waitForTimeout(4000);

  const body = page.locator(".sp-root");
  // Console output from the analysis
  await expect(body).toContainText("total_margin", { timeout: 30_000 });
  // Table output (column header from sp.ui.table)
  await expect(body).toContainText("revenue");
  // Interactive slider label
  await expect(body).toContainText("Margin alert threshold");
  // Chart: cells virtualize, so scroll through the notebook to mount the
  // chart cell, then look for the vega/altair render (canvas or svg marks).
  for (let i = 0; i < 6; i++) {
    await page.mouse.wheel(0, 800);
    await page.waitForTimeout(600);
    const n = await page.locator(".sp-root canvas, .sp-root .vega-embed, .sp-root svg.marks, .sp-root [aria-label*=chart i]").count();
    if (n > 0) break;
  }
  const chartNodes = await page.locator(".sp-root canvas, .sp-root .vega-embed, .sp-root svg.marks, .sp-root [aria-label*=chart i]").count();
  expect(chartNodes, "altair chart should render").toBeGreaterThan(0);
});
