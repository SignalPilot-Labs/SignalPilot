import { describe, expect, it } from "vitest";

import { gridHeight, layoutModeForWidth, placeTiles, tileRect } from "./layout";
import type { DashboardChart, DashboardSpec } from "./schema";

function chart(id: string, type: DashboardChart["type"], grid?: { x: number; y: number; w: number; h: number }): DashboardChart {
  const base = { id, title: id, dataset: "d", grid } as Record<string, unknown>;
  if (type === "kpi") return { ...base, type, value: { column: "v" } } as DashboardChart;
  if (type === "table") return { ...base, type, columns: [{ column: "v" }] } as DashboardChart;
  if (type === "pie") return { ...base, type, label: "l", value: { column: "v" } } as DashboardChart;
  if (type === "scatter") return { ...base, type, x: { column: "x" }, y: { column: "v" } } as DashboardChart;
  return { ...base, type, x: { column: "x" }, y: [{ column: "v" }] } as DashboardChart;
}

function spec(charts: DashboardChart[], rowHeight?: number): DashboardSpec {
  return { version: 1, title: "T", datasets: { d: { rows: [] } }, charts, layout: rowHeight ? { rowHeight } : undefined };
}

describe("placeTiles", () => {
  it("places explicit grids exactly", () => {
    const tiles = placeTiles(spec([chart("a", "kpi", { x: 3, y: 1, w: 3, h: 2 })]));
    expect(tiles).toEqual([{ chartId: "a", x: 3, y: 1, w: 3, h: 2 }]);
  });

  it("auto-flows after the placed tiles with per-type sizes and wraps at 12", () => {
    const tiles = placeTiles(
      spec([
        chart("placed", "line", { x: 0, y: 0, w: 12, h: 3 }),
        chart("k1", "kpi"),
        chart("k2", "kpi"),
        chart("b1", "bar"),
        chart("p1", "pie"),
        chart("t1", "table"),
        chart("s1", "scatter"),
      ]),
    );
    expect(tiles).toEqual([
      { chartId: "placed", x: 0, y: 0, w: 12, h: 3 },
      { chartId: "k1", x: 0, y: 3, w: 3, h: 2 },
      { chartId: "k2", x: 3, y: 3, w: 3, h: 2 },
      { chartId: "b1", x: 6, y: 3, w: 6, h: 4 },
      { chartId: "p1", x: 0, y: 7, w: 6, h: 4 },
      { chartId: "t1", x: 0, y: 11, w: 12, h: 5 },
      { chartId: "s1", x: 0, y: 16, w: 6, h: 4 },
    ]);
  });

  it("filters by chart ids and can ignore grids", () => {
    const tiles = placeTiles(
      spec([chart("a", "kpi", { x: 6, y: 6, w: 3, h: 2 }), chart("b", "bar", { x: 0, y: 0, w: 6, h: 4 }), chart("c", "kpi")]),
      { chartIds: ["a", "c"], ignoreGrid: true },
    );
    expect(tiles).toEqual([
      { chartId: "a", x: 0, y: 0, w: 3, h: 2 },
      { chartId: "c", x: 3, y: 0, w: 3, h: 2 },
    ]);
  });

  it("clamps a grid that overflows the 12 columns", () => {
    const tiles = placeTiles(spec([chart("a", "bar", { x: 10, y: 0, w: 6, h: 2 })]));
    expect(tiles[0]).toMatchObject({ x: 10, w: 2 });
  });
});

describe("responsive modes", () => {
  const charts = [
    chart("k1", "kpi", { x: 0, y: 0, w: 3, h: 2 }),
    chart("k2", "kpi", { x: 3, y: 0, w: 3, h: 2 }),
    chart("l1", "line", { x: 0, y: 2, w: 8, h: 4 }),
    chart("t1", "table"),
  ];

  it("maps widths to modes", () => {
    expect(layoutModeForWidth(1280)).toBe("full");
    expect(layoutModeForWidth(720)).toBe("full");
    expect(layoutModeForWidth(719)).toBe("compact");
    expect(layoutModeForWidth(420)).toBe("compact");
    expect(layoutModeForWidth(419)).toBe("narrow");
  });

  it("full honors grids", () => {
    expect(placeTiles(spec(charts), { mode: "full" })[2]).toEqual({ chartId: "l1", x: 0, y: 2, w: 8, h: 4 });
  });

  it("compact ignores grids: kpi half width, everything else full width", () => {
    expect(placeTiles(spec(charts), { mode: "compact" })).toEqual([
      { chartId: "k1", x: 0, y: 0, w: 6, h: 2 },
      { chartId: "k2", x: 6, y: 0, w: 6, h: 2 },
      { chartId: "l1", x: 0, y: 2, w: 12, h: 4 },
      { chartId: "t1", x: 0, y: 6, w: 12, h: 5 },
    ]);
  });

  it("narrow stacks every tile full width", () => {
    expect(placeTiles(spec(charts), { mode: "narrow" })).toEqual([
      { chartId: "k1", x: 0, y: 0, w: 12, h: 2 },
      { chartId: "k2", x: 0, y: 2, w: 12, h: 2 },
      { chartId: "l1", x: 0, y: 4, w: 12, h: 4 },
      { chartId: "t1", x: 0, y: 8, w: 12, h: 5 },
    ]);
  });
});

describe("tileRect / gridHeight", () => {
  it("converts grid units to pixels with a 12px gap", () => {
    // 12 columns * 100 + 11 gaps * 12 = 1332
    const rect = tileRect({ chartId: "a", x: 1, y: 1, w: 2, h: 2 }, 1332, 72);
    expect(rect).toEqual({ x: 112, y: 84, width: 212, height: 156 });
    expect(gridHeight([{ chartId: "a", x: 0, y: 0, w: 1, h: 3 }], 72)).toBe(3 * 72 + 2 * 12);
    expect(gridHeight([], 72)).toBe(0);
  });
});
