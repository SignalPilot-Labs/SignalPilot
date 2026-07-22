// Debug run for the multipart eval upload — logs console + request failures.
import { chromium } from "playwright";

const zipPath = process.env.EVAL_TEST_ZIP;
const browser = await chromium.launch();
const page = await browser.newPage();
page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") console.log("CONSOLE:", m.type(), m.text()); });
page.on("requestfailed", (r) => console.log("REQFAIL:", r.method(), r.url().slice(0, 120), r.failure()?.errorText));
page.on("response", (r) => { if (r.status() >= 400) console.log("HTTP", r.status(), r.request().method(), r.url().slice(0, 140)); });
try {
  await page.goto("http://localhost:3200/evals/upload", { waitUntil: "domcontentloaded" });
  await page.waitForSelector('input[type="file"]', { state: "attached" });
  await page.setInputFiles('input[type="file"]', zipPath);
  await page.click('button:has-text("Upload eval")');
  await page.waitForSelector("text=the team has been notified", { timeout: 120000 });
  console.log("SUCCESS", await page.textContent("code"));
} catch (err) {
  console.error("FAILED:", err.message.split("\n")[0]);
  process.exitCode = 1;
} finally {
  await browser.close();
}
