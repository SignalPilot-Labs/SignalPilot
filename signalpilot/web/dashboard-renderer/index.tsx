"use client";

/**
 * DashboardRenderer: React host for a dashboard spec. Renders the title,
 * description, filter bar and the 12-column grid of tiles.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { EChartsTile } from "./charts/echarts-tile";
import { KpiTile } from "./charts/kpi";
import { isOptionChart } from "./charts/options";
import { TableTile } from "./charts/table";
import type { DatasetRows } from "./datasets";
import { FilterBar } from "./filters";
import { GRID_COLUMNS, GRID_GAP, layoutModeForWidth, placeTiles, rowHeightOf, type LayoutMode } from "./layout";
import {
  chartIsFailed,
  prepareChartRows,
  type ChartIssue,
  type FilterState,
} from "./prepare";
import type { DashboardChart, DashboardSpec } from "./schema";
import { themeTokens, type DashboardTheme } from "./theme";

export type { DatasetRows } from "./datasets";
export type { ChartIssue, FilterState } from "./prepare";
export type { DashboardChart, DashboardDataset, DashboardSpec, DashboardSqlDataset } from "./schema";
export type { DashboardTheme } from "./theme";
export { isSqlDataset, validateDashboardSpec } from "./schema";
export { parseDatasetCsv, datasetFileRefs, datasetSnapshotPath, inlineDatasets } from "./datasets";
export { prepareChartRows, chartIsFailed } from "./prepare";
export { placeTiles, layoutModeForWidth } from "./layout";
export type { LayoutMode } from "./layout";
export { formatValue, formatAxisDate } from "./format";
export { buildChartOption } from "./charts/options";

export type RenderStatus = {
  rendered: string[];
  failed: { id: string; code: string; message: string }[];
};

export type DashboardRendererProps = {
  spec: DashboardSpec;
  datasets: Record<string, DatasetRows>;
  theme?: DashboardTheme;
  filterState?: FilterState;
  onFilterStateChange?: (state: FilterState) => void;
  onStatus?: (status: RenderStatus) => void;
  showFilters?: boolean;
};

function themeStyle(theme: DashboardTheme): CSSProperties {
  const tokens = themeTokens(theme);
  return {
    "--sp-dash-bg": tokens.background,
    "--sp-dash-surface": tokens.surface,
    "--sp-dash-border": tokens.border,
    "--sp-dash-text": tokens.text,
    "--sp-dash-text-secondary": tokens.textSecondary,
    "--sp-dash-text-muted": tokens.textMuted,
    "--sp-dash-grid": tokens.gridLine,
    "--sp-dash-error": tokens.error,
    "--sp-dash-error-bg": tokens.errorBackground,
    "--sp-dash-accent": tokens.palette[0],
    fontFamily: tokens.fontFamily,
    color: tokens.text,
  } as CSSProperties;
}

function TileBody({
  chart,
  rows,
  issues,
  theme,
}: {
  chart: DashboardChart;
  rows: DatasetRows;
  issues: ChartIssue[];
  theme: DashboardTheme;
}) {
  if (chartIsFailed(issues)) {
    return (
      <div
        data-dashboard-tile-error=""
        className="rounded bg-[var(--sp-dash-error-bg)] px-2 py-1.5 text-[12px] leading-4 text-[var(--sp-dash-error)]"
      >
        {issues.map((issue) => issue.message).join(" ")}
      </div>
    );
  }
  if (chart.type === "kpi") return <KpiTile chart={chart} rows={rows} />;
  if (chart.type === "table") return <TableTile chart={chart} rows={rows} />;
  if (isOptionChart(chart)) return <EChartsTile chart={chart} rows={rows} theme={theme} />;
  return null;
}

export function DashboardRenderer({
  spec,
  datasets,
  theme = "light",
  filterState,
  onFilterStateChange,
  onStatus,
  showFilters,
}: DashboardRendererProps) {
  const [localFilterState, setLocalFilterState] = useState<FilterState>({});
  const effectiveFilterState = filterState ?? localFilterState;
  const setFilterState = (next: FilterState) => {
    if (!filterState) setLocalFilterState(next);
    onFilterStateChange?.(next);
  };

  const gridRef = useRef<HTMLDivElement | null>(null);
  const [mode, setMode] = useState<LayoutMode>("full");
  useEffect(() => {
    const element = gridRef.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const update = () => setMode(layoutModeForWidth(element.getBoundingClientRect().width));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const tiles = useMemo(() => placeTiles(spec, { mode }), [spec, mode]);
  const rowHeight = rowHeightOf(spec);
  const prepared = useMemo(
    () =>
      spec.charts.map((chart) => ({
        chart,
        ...prepareChartRows(chart, spec, datasets, effectiveFilterState),
      })),
    [spec, datasets, effectiveFilterState],
  );
  const status = useMemo<RenderStatus>(() => {
    const rendered: string[] = [];
    const failed: RenderStatus["failed"] = [];
    for (const entry of prepared) {
      if (chartIsFailed(entry.issues)) {
        const first = entry.issues.find((issue) => chartIsFailed([issue])) ?? entry.issues[0];
        failed.push({ id: entry.chart.id, code: first.code, message: first.message });
      } else {
        rendered.push(entry.chart.id);
      }
    }
    return { rendered, failed };
  }, [prepared]);
  useEffect(() => {
    onStatus?.(status);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  const byId = new Map(prepared.map((entry) => [entry.chart.id, entry]));
  return (
    <div
      data-dashboard-renderer=""
      data-theme={theme}
      style={themeStyle(theme)}
      className="flex w-full flex-col gap-3 bg-[var(--sp-dash-bg)] p-4"
    >
      <header className="flex flex-col gap-1">
        <h2 className="text-[18px] font-semibold leading-6 text-[var(--sp-dash-text)]">{spec.title}</h2>
        {spec.description ? (
          <p className="text-[13px] leading-5 text-[var(--sp-dash-text-secondary)]">{spec.description}</p>
        ) : null}
      </header>
      {showFilters !== false ? (
        <FilterBar
          spec={spec}
          datasets={datasets}
          filterState={effectiveFilterState}
          onChange={setFilterState}
        />
      ) : null}
      <div
        ref={gridRef}
        data-dashboard-grid=""
        data-layout-mode={mode}
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${GRID_COLUMNS}, minmax(0, 1fr))`,
          gridAutoRows: `${rowHeight}px`,
          gap: GRID_GAP,
        }}
      >
        {tiles.map((tile) => {
          const entry = byId.get(tile.chartId);
          if (!entry) return null;
          const { chart, rows, issues } = entry;
          return (
            <section
              key={chart.id}
              data-chart-id={chart.id}
              data-chart-type={chart.type}
              title={chart.description}
              style={{
                gridColumn: `${tile.x + 1} / span ${tile.w}`,
                gridRow: `${tile.y + 1} / span ${tile.h}`,
              }}
              className="flex min-h-0 min-w-0 flex-col gap-1 overflow-hidden rounded-lg border border-[var(--sp-dash-border)] bg-[var(--sp-dash-surface)] p-3"
            >
              <h3 className="truncate text-[13px] font-semibold leading-4 text-[var(--sp-dash-text)]">
                {chart.title}
              </h3>
              <div className="min-h-0 flex-1">
                <TileBody chart={chart} rows={rows} issues={issues} theme={theme} />
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

export default DashboardRenderer;
