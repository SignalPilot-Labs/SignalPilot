"use client";

import type { DatasetRows } from "../datasets";
import { formatValue } from "../format";
import type { KpiChart } from "../schema";

/**
 * One headline cell plus an optional comparison line. A numeric cell renders
 * with its `format`; a text cell (for example `top_region = "South"`) renders
 * verbatim at the same size, so `formatValue` decides per cell.
 */
export function KpiTile({ chart, rows }: { chart: KpiChart; rows: DatasetRows }) {
  const first = rows[0];
  const value = formatValue(first?.[chart.value.column], chart.value.format);
  const comparison = chart.comparison;
  return (
    <div
      data-dashboard-tile="kpi"
      className="flex h-full min-w-0 flex-col justify-center gap-1 overflow-hidden"
      style={{ containerType: "inline-size" }}
    >
      <div
        className="min-w-0 break-words font-semibold tabular-nums text-[var(--sp-dash-text)]"
        style={{ fontSize: "clamp(16px, 9cqw, 28px)", lineHeight: 1.1 }}
        title={value}
      >
        {value}
      </div>
      {comparison && first ? (
        <div className="truncate text-[12px] text-[var(--sp-dash-text-muted)]">
          {comparison.label ?? comparison.column}:{" "}
          {formatValue(first[comparison.column], comparison.format)}
        </div>
      ) : null}
    </div>
  );
}
