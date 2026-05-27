import { test } from "@playwright/test";

const URL = "/projects?project=3781d00d-3f10-4139-9b70-2e4cd9c42c63&branch=main&file=models/schema.yml";

test("schema.yml fetch debug", async ({ page }) => {
  test.setTimeout(30_000);

  page.on("console", (msg) => {
    const t = msg.text();
    if (t.includes("[raw-editor]")) console.log(`BROWSER: ${t}`);
  });
  page.on("response", (r) => {
    if (r.url().includes("file_details")) {
      console.log(`NETWORK: ${r.status()} ${r.url().split("?")[0].slice(-40)}`);
    }
  });

  await page.goto(URL, { waitUntil: "domcontentloaded" });
  await page.getByText("running").waitFor({ timeout: 30_000 }).catch(() => {});
  await page.waitForTimeout(10000);
});
