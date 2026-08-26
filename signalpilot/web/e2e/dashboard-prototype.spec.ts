import { expect, test } from "@playwright/test";

test("renders the five-component dashboard fixture", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto("/dashboard-prototype/five-components");

  await expect(
    page.getByRole("heading", { name: "Five component fixture" }),
  ).toBeVisible();
  for (const renderer of ["kpi", "table", "bar", "line", "area"]) {
    await expect(
      page.locator(`[data-dashboard-renderer="${renderer}"]`),
    ).toBeVisible();
  }
  await expect(page.locator('[data-dashboard-renderer="kpi"]')).toContainText(
    "1,595,000",
  );
  await expect(
    page.locator('[data-dashboard-renderer="table"] tbody tr'),
  ).toHaveCount(4);
  await expect(page.locator("canvas")).toHaveCount(3);
  expect(pageErrors).toEqual([]);
});

test("cross-filters both Lightdash charts, drills, and expands detail rows", async ({
  page,
}) => {
  const lightdashRequests: string[] = [];
  const pageErrors: string[] = [];

  page.on("request", (request) => {
    const hostname = new URL(request.url()).hostname;
    if (hostname.includes("lightdash")) lightdashRequests.push(request.url());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto("/dashboard-prototype");

  await expect(
    page.getByRole("heading", { name: "Revenue performance" }),
  ).toBeVisible();
  await expect(page.locator("canvas")).toHaveCount(2);
  await page.getByLabel("Region filter").selectOption("Southeast");
  await expect(page.getByText("region = Southeast")).toBeVisible();
  const filteredCanvas = await page.locator("canvas").first().elementHandle();
  expect(filteredCanvas).not.toBeNull();
  await page.getByRole("button", { name: "Clear" }).click();
  await expect(page.getByText("region = Southeast")).toHaveCount(0);
  await filteredCanvas!.waitForElementState("hidden");
  await expect(page.locator("canvas")).toHaveCount(2);

  const canvas = page.locator("canvas").first();
  await expect(canvas).toBeVisible();

  const bounds = await canvas.boundingBox();
  expect(bounds).not.toBeNull();
  await canvas.click({
    position: {
      x: Math.round(bounds!.width * 0.19),
      y: Math.round(bounds!.height * 0.5),
    },
  });

  await expect(page.getByTestId("dashboard-chart-reference")).toContainText(
    "Northeast",
  );
  await expect(page.getByText("region = Northeast")).toBeVisible();

  await page.getByRole("button", { name: "Drill into customers" }).click();
  await expect(
    page.getByText("All regions / Northeast / Customers"),
  ).toBeVisible();
  await expect(page.getByText("Customers in Northeast")).toHaveCount(2);

  await page.getByRole("row", { name: /Northeast/ }).click();
  await expect(page.getByText("Acme Waste")).toBeVisible();
  expect(lightdashRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
});
