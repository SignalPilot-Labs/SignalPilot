"use client";

/**
 * Thin echarts-for-react tile. The wrapper pattern follows Lightdash's
 * EChartsReactWrapper (see ../UPSTREAM.md and ../LICENSE.lightdash).
 */
import EChartsReact from "echarts-for-react";
import { useMemo } from "react";

import type { DatasetRows } from "../datasets";
import type { DashboardTheme } from "../theme";
import { buildChartOption, type ChartOptionChart } from "./options";

export function EChartsTile({
  chart,
  rows,
  theme,
}: {
  chart: ChartOptionChart;
  rows: DatasetRows;
  theme: DashboardTheme;
}) {
  const option = useMemo(() => buildChartOption(chart, rows, theme), [chart, rows, theme]);
  return (
    <div data-dashboard-tile={chart.type} className="h-full min-h-0 w-full">
      <EChartsReact
        option={option}
        notMerge
        lazyUpdate
        style={{ width: "100%", height: "100%" }}
        opts={{ renderer: "svg" }}
      />
    </div>
  );
}
