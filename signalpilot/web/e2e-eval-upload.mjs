// One-off e2e for the hidden /evals/upload page against the dockerized eval stack.
// Run: node e2e-eval-upload.mjs
import { chromium } from "playwright";

const zipPath = process.env.EVAL_TEST_ZIP;
const browser = await chromium.launch();
const page = await browser.newPage();
try {
  const baseUrl = process.env.EVAL_TEST_BASE_URL || "http://localhost:3200";
  await page.goto(`${baseUrl}/evals/upload`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('input[type="file"]', { state: "attached" });
  await page.screenshot({ path: "e2e-eval-01-ready.png" });

  await page.setInputFiles('input[type="file"]', zipPath);
  await page.fill("textarea", "e2e test — Snowflake dialect, see README");
  await page.screenshot({ path: "e2e-eval-02-file-selected.png" });

  await page.click('button:has-text("Upload eval")');
  await page.waitForSelector("text=the team has been notified", { timeout: 30000 });
  await page.screenshot({ path: "e2e-eval-03-done.png" });

  const ref = await page.textContent("code");
  console.log("SUCCESS reference_id:", ref);
} catch (err) {
  await page.screenshot({ path: "e2e-eval-fail.png" });
  console.error("FAILED:", err.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}
