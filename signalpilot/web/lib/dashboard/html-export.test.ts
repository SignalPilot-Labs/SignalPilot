import { afterEach, describe, expect, it } from "vitest";

import { captureDashboardHtmlExport } from "~/lib/dashboard/html-export";

describe("dashboard HTML export", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it("serializes the live dashboard DOM instead of rebuilding another interface", () => {
    const root = document.createElement("div");
    root.className = "dashboard-runtime-class";
    root.innerHTML = `
      <header><h1>Revenue dashboard</h1><button data-dashboard-export-exclude>Export</button></header>
      <section class="chart-tile"><h2>Revenue by region</h2><strong>$1,234.50</strong></section>
      <select><option>North</option><option selected>South</option></select>`;
    document.body.append(root);

    const html = captureDashboardHtmlExport({
      root,
      title: "Revenue dashboard",
      sourceUrl: "https://signalpilot.test/dashboards/dashboard-1",
      exportedAt: new Date("2026-08-25T15:00:00Z"),
    });

    expect(html).toContain("dashboard-runtime-class");
    expect(html).toContain("Revenue by region");
    expect(html).toContain("$1,234.50");
    expect(html).toContain('<option selected="">South</option>');
    expect(html).not.toContain(">Export</button>");
    expect(html).not.toContain("fetch(");
  });
});
