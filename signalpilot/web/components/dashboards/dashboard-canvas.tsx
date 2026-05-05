"use client";

import type { DashboardDefinition } from "@/lib/dashboards/types";
import { DashboardChartCard } from "./dashboard-chart-card";

export function DashboardCanvas({ dashboard }: { dashboard: DashboardDefinition }) {
  const cols = dashboard.layout?.columns ?? 12;
  const rowH = dashboard.layout?.rowHeight ?? 80;

  const allDefault = dashboard.charts.every(
    (c) => c.position.x === 0 && c.position.y === 0,
  );

  if (allDefault && dashboard.charts.length > 1) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {dashboard.charts.map((chart) => (
          <DashboardChartCard key={chart.id} chart={chart} />
        ))}
      </div>
    );
  }

  const maxRow = dashboard.charts.reduce(
    (max, c) => Math.max(max, c.position.y + c.position.h),
    0,
  );

  return (
    <div
      className="relative"
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${cols}, 1fr)`,
        gridAutoRows: `${rowH}px`,
        gap: "16px",
        minHeight: maxRow * rowH + (maxRow - 1) * 16,
      }}
    >
      {dashboard.charts.map((chart) => {
        const { x, y, w, h } = chart.position;
        return (
          <div
            key={chart.id}
            style={{
              gridColumn: `${x + 1} / span ${w}`,
              gridRow: `${y + 1} / span ${h}`,
            }}
          >
            <DashboardChartCard chart={chart} />
          </div>
        );
      })}
    </div>
  );
}
