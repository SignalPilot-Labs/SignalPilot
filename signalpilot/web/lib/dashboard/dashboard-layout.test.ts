import { describe, expect, it } from "vitest";

import {
  normalizedTileSpan,
  orderDashboardTiles,
} from "~/lib/dashboard/dashboard-layout";
import type { DashboardTileDefinition } from "~/lib/dashboard/contracts";

function tile(
  uuid: string,
  x: number,
  y: number,
  w: number,
): DashboardTileDefinition {
  return {
    uuid,
    tileSlug: uuid,
    type: "saved_chart",
    x,
    y,
    h: 10,
    w,
    properties: { chartSlug: uuid },
    chartId: uuid,
  };
}

describe("dashboard canvas layout", () => {
  it("preserves rows that already fill all 36 columns", () => {
    const row = [
      tile("kpi", 0, 0, 8),
      tile("table", 8, 0, 14),
      tile("bar", 22, 0, 14),
    ];
    expect(row.map((item) => normalizedTileSpan(item, row))).toEqual([
      8, 14, 14,
    ]);
  });

  it("expands incomplete rows to fill the canvas", () => {
    const single = tile("table", 0, 20, 18);
    expect(normalizedTileSpan(single, [single])).toBe(36);

    const row = [tile("left", 0, 10, 12), tile("right", 12, 10, 12)];
    expect(row.map((item) => normalizedTileSpan(item, row))).toEqual([18, 18]);
  });

  it("orders authored tiles by row and horizontal position", () => {
    const tiles = [
      tile("last", 18, 10, 18),
      tile("first", 0, 0, 36),
      tile("middle", 0, 10, 18),
    ];
    expect(orderDashboardTiles(tiles).map((item) => item.uuid)).toEqual([
      "first",
      "middle",
      "last",
    ]);
  });
});
