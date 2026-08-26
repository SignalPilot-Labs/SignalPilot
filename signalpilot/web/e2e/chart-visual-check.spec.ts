import { test, expect } from "@playwright/test";
test("chart cell renders without error (replay + live kernel)", async ({ page }) => {
  test.setTimeout(150_000);
  const pid = "5a6f0ae2-2e05-400f-b5df-99079d11d865";
  await page.goto(`/projects?project=${pid}&branch=main&file=signalpilot-agent%2Fdeep_analysis_demo.py`, { waitUntil: "domcontentloaded" });
  await page.locator(".sp-root").waitFor({ timeout: 120_000 });
  await page.waitForTimeout(10000); // kernel attach + rerun
  const chartCode = page.getByText("altair_chart").first();
  await chartCode.scrollIntoViewIfNeeded().catch(() => {});
  await page.mouse.move(700, 400); await page.mouse.wheel(0, 400);
  await page.waitForTimeout(4000);
  const text = await page.locator(".sp-root").innerText();
  expect(text, "no arrow parse error").not.toContain("metadata bytes");
  const marks = await page.locator(".sp-root .vega-embed, .sp-root canvas.marks, .sp-root svg.marks").count();
  console.log("vega nodes:", marks);
  expect(marks, "vega chart should mount").toBeGreaterThan(0);
  await page.screenshot({ path: "chart-fixed.png" });
});
