import type { DashboardTileDefinition } from "~/lib/dashboard/contracts";

const CANVAS_COLUMNS = 36;

export function orderDashboardTiles(
  tiles: DashboardTileDefinition[],
): DashboardTileDefinition[] {
  return [...tiles].sort((left, right) =>
    left.y === right.y ? left.x - right.x : left.y - right.y,
  );
}

export function normalizedTileSpan(
  tile: DashboardTileDefinition,
  rowTiles: DashboardTileDefinition[],
): number {
  const ordered = orderDashboardTiles(rowTiles);
  const index = ordered.findIndex((candidate) => candidate.uuid === tile.uuid);
  if (index < 0) return Math.min(CANVAS_COLUMNS, Math.max(1, tile.w));

  const totalWidth = ordered.reduce(
    (total, candidate) => total + candidate.w,
    0,
  );
  if (totalWidth <= 0) return CANVAS_COLUMNS;

  const widthBefore = ordered
    .slice(0, index)
    .reduce((total, candidate) => total + candidate.w, 0);
  const widthThrough = widthBefore + tile.w;
  const start = Math.round((widthBefore / totalWidth) * CANVAS_COLUMNS);
  const end =
    index === ordered.length - 1
      ? CANVAS_COLUMNS
      : Math.round((widthThrough / totalWidth) * CANVAS_COLUMNS);
  return Math.max(1, end - start);
}
