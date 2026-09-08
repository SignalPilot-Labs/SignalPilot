// @vitest-environment node
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { datasetSnapshotPath, parseDatasetCsv, type DatasetRows } from "../datasets";
import type { DashboardSpec } from "../schema";
import { isSqlDataset, validateDashboardSpec } from "../schema";
import { composeDashboardSvg, nestSvg } from "./compose";
import { fontFiles, parseArgs, renderFromPayload } from "./render-cli";
import { truncateText, wrapText } from "./svg-tiles";

const root = join(__dirname, "..");
const fixtures = join(root, "fixtures");

function loadFixture(): { spec: DashboardSpec; datasets: Record<string, DatasetRows> } {
  const raw = JSON.parse(readFileSync(join(fixtures, "revenue.dashboard.json"), "utf8"));
  const validation = validateDashboardSpec(raw);
  if (!validation.ok) throw new Error(validation.errors.join("\n"));
  const spec = validation.spec;
  const datasets: Record<string, DatasetRows> = {};
  for (const [name, dataset] of Object.entries(spec.datasets)) {
    if (!isSqlDataset(dataset)) {
      datasets[name] = dataset.rows;
      continue;
    }
    const file = join(fixtures, datasetSnapshotPath(name).replace(/^artifacts\//, ""));
    datasets[name] = parseDatasetCsv(readFileSync(file, "utf8"));
  }
  return { spec, datasets };
}

describe("svg text helpers", () => {
  it("truncates and wraps by estimated width", () => {
    expect(truncateText("short", 100, 12)).toBe("short");
    expect(truncateText("a very long label indeed", 40, 12)).toMatch(/…$/);
    expect(wrapText("one two three four", 40, 12, 2)).toHaveLength(2);
  });

  it("nests an svg document at a position", () => {
    const nested = nestSvg('<svg width="10" height="10" xmlns="http://www.w3.org/2000/svg"><g/></svg>', 5, 6, 20, 30);
    expect(nested.startsWith('<svg x="5.0" y="6.0" width="20.0" height="30.0" xmlns=')).toBe(true);
  });
});

describe("composeDashboardSvg", () => {
  it("renders every fixture tile with a data-chart-id", () => {
    const { spec, datasets } = loadFixture();
    const result = composeDashboardSvg({ spec, datasets, width: 1280, theme: "light" });
    expect(result.svg.startsWith("<svg")).toBe(true);
    for (const chart of spec.charts) {
      expect(result.svg).toContain(`data-chart-id="${chart.id}"`);
    }
    expect(result.rendered.sort()).toEqual(spec.charts.map((chart) => chart.id).sort());
    expect(result.failed).toEqual([]);
    expect(result.width).toBe(1280);
    expect(result.height).toBeGreaterThan(600);
    expect(result.svg).toContain("Revenue overview 2024");
    expect(result.svg).toContain("Period: 2024-01-01 to 2024-12-01");
    expect(result.svg).toContain("$5,896,400");
  });

  it("re-flows selected charts and reports failed tiles", () => {
    const { spec, datasets } = loadFixture();
    const broken: DashboardSpec = {
      ...spec,
      charts: [...spec.charts, { id: "broken", type: "kpi", title: "Broken", dataset: "nope", value: { column: "x" } }],
    };
    const result = composeDashboardSvg({ spec: broken, datasets, chartIds: ["kpi_revenue", "broken"], width: 800, theme: "dark" });
    expect(result.rendered).toEqual(["kpi_revenue"]);
    expect(result.failed).toEqual([
      expect.objectContaining({ id: "broken", code: "missing_dataset" }),
    ]);
    expect(result.svg).not.toContain('data-chart-id="revenue_trend"');
    expect(result.svg).toContain("Chart &quot;broken&quot;");
    expect(result.svg).toContain('fill="#f97066"');
  });
});

describe("render-cli in-process", () => {
  it("parses arguments", () => {
    expect(parseArgs(["--out", "x.png", "--width", "900", "--theme", "dark"])).toEqual({ out: "x.png", width: 900, theme: "dark" });
    expect(parseArgs(["--out=y.png", "--width=abc", "--theme=blue"])).toEqual({ out: "y.png", width: 1280, theme: "light" });
  });

  it("finds the bundled fonts", () => {
    const fonts = fontFiles(join(root, "print"));
    expect(fonts.length).toBeGreaterThan(0);
    expect(fonts[0]).toMatch(/DMSans.*\.ttf$/);
  });

  it("renders the fixture to a PNG of the requested width", () => {
    const { spec, datasets } = loadFixture();
    const fonts = fontFiles(root);
    const outcome = renderFromPayload({ spec, datasets, chart_ids: null }, { width: 1000, theme: "light" }, fonts);
    expect(outcome.ok).toBe(true);
    if (!outcome.ok) return;
    const png = outcome.png;
    expect([...png.subarray(0, 8)]).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    // IHDR width is the big-endian uint32 at byte 16.
    expect(png.readUInt32BE(16)).toBe(1000);
    expect(png.readUInt32BE(20)).toBe(outcome.height);
    expect(outcome.rendered).toHaveLength(spec.charts.length);
  });

  it("rejects an invalid spec with errors", () => {
    const outcome = renderFromPayload({ spec: { version: 1 } }, { width: 800, theme: "light" }, []);
    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.errors.some((error) => error.includes("must have required property"))).toBe(true);
  });
});

describe("print path isolation", () => {
  const forbidden = [/from\s+["']~\//, /from\s+["']react["']/, /from\s+["']react\//, /from\s+["']next/, /from\s+["']echarts-for-react/, /require\(["']react["']\)/];

  function walk(dir: string, out: string[]): string[] {
    for (const name of readdirSync(dir)) {
      const full = join(dir, name);
      if (name === "node_modules" || name === "dist" || name === "fixtures" || name === "fonts") continue;
      if (statSync(full).isDirectory()) walk(full, out);
      else if (/\.ts$/.test(name) && !/\.test\.ts$/.test(name)) out.push(full);
    }
    return out;
  }

  it("print-path modules import no React, Next, alias or echarts-for-react", () => {
    const files = walk(root, []);
    expect(files.length).toBeGreaterThan(8);
    const violations: string[] = [];
    for (const file of files) {
      const text = readFileSync(file, "utf8");
      for (const pattern of forbidden) {
        if (pattern.test(text)) violations.push(`${file}: ${pattern}`);
      }
    }
    expect(violations).toEqual([]);
  });
});
