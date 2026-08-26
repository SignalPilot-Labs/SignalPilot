"use client";

import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

import { useEffect, useMemo, useState } from "react";
import { Responsive, WidthProvider, type Layouts } from "react-grid-layout";

import { DashboardRenderer } from "~/components/dashboard/dashboard-renderer";
import {
  combineDrillFilters,
  createTemporaryDashboardFilter,
} from "~/dashboard/lightdash/filter-interactions";
import type {
  ChartDefinition,
  DashboardChartReference,
  DashboardDataSource,
  DashboardDefinition,
  DashboardFilter,
  DashboardQueryResult,
  DashboardTileDefinition,
} from "~/lib/dashboard/contracts";
import { mockDashboardRegions } from "~/lib/dashboard/mock-dashboard-data-source";

import styles from "./dashboard-prototype.module.css";

const ResponsiveGridLayout = WidthProvider(Responsive);

export function SignalPilotDashboardPrototype({
  spec,
  dataSource,
  dashboardVersionId,
}: {
  spec: DashboardDefinition;
  dataSource: DashboardDataSource;
  dashboardVersionId: string;
}) {
  const [results, setResults] = useState<Record<string, DashboardQueryResult>>(
    {},
  );
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<DashboardFilter[]>([]);
  const [drillPath, setDrillPath] = useState<
    Array<{ field: string; value: unknown }>
  >([]);
  const [expandedRegions, setExpandedRegions] = useState<string[]>([]);
  const [reference, setReference] = useState<DashboardChartReference | null>(
    null,
  );

  const selectedRegion = filters.find(({ field }) => field === "region")
    ?.value as string | undefined;
  const isDrilled = drillPath.length > 0;

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    Promise.all(
      spec.tiles.map(async (tile) => {
        const chart = spec.charts.find(({ id }) => id === tile.chartId);
        if (!chart) throw new Error(`Missing chart '${tile.chartId}'`);
        return [
          tile.uuid,
          await dataSource.loadTile(
            tile,
            chart,
            { filters, drillPath },
            controller.signal,
          ),
        ] as const;
      }),
    )
      .then((entries) => setResults(Object.fromEntries(entries)))
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setError(
          cause instanceof Error ? cause.message : "Dashboard query failed",
        );
      });
    return () => controller.abort();
  }, [dataSource, drillPath, filters, spec.charts, spec.tiles]);

  const layouts = useMemo<Layouts>(
    () => ({
      lg: spec.tiles.map((tile, index) => ({
        i: tile.uuid,
        x: tile.x,
        y: tile.y,
        w: tile.w,
        h: tile.h,
      })),
      md: spec.tiles.map((tile, index) => ({
        i: tile.uuid,
        x: index * 10,
        y: 0,
        w: 10,
        h: 15,
      })),
      sm: spec.tiles.map((tile, index) => ({
        i: tile.uuid,
        x: 0,
        y: index * 15,
        w: 12,
        h: 15,
      })),
    }),
    [spec.tiles],
  );

  const applyRegion = (region?: string) => {
    setFilters(
      region ? [createTemporaryDashboardFilter("region", region)] : [],
    );
    setDrillPath([]);
    setReference(null);
  };

  const handleMarkClick = (
    tile: DashboardTileDefinition,
    chart: ChartDefinition,
    result: DashboardQueryResult,
    selectedMark: Record<string, unknown>,
  ) => {
    const region = selectedMark.region;
    const nextFilters =
      typeof region === "string"
        ? combineDrillFilters(filters, selectedMark, ["region"])
        : filters;
    if (typeof region === "string") setFilters(nextFilters);
    setReference({
      dashboardUuid: spec.signalPilot.dashboardId,
      dashboardVersionId,
      tileUuid: tile.uuid,
      chartUuid: chart.id,
      dashboardResultId: result.resultId,
      executionId: result.executionId,
      dashboardFilters: Object.fromEntries(
        nextFilters.map((filter) => [filter.field, filter.value]),
      ),
      drillPath,
      selectedMark,
      provenanceRef: chart.signalPilot.provenanceRef,
    });
  };

  const drillIntoCustomers = () => {
    if (!selectedRegion) return;
    setDrillPath([{ field: "region", value: selectedRegion }]);
  };

  return (
    <div className={styles.page} data-testid="dashboard-prototype">
      <div className={styles.header}>
        <div>
          <div className={styles.eyebrow}>Lightdash interaction prototype</div>
          <h1 className={styles.title}>{spec.name}</h1>
          {spec.description ? (
            <p className={styles.description}>{spec.description}</p>
          ) : null}
        </div>
        <div className={styles.badge}>shared runtime · native renderer</div>
      </div>

      <div className={styles.toolbar}>
        <label className={styles.filterLabel}>
          Region
          <select
            aria-label="Region filter"
            className={styles.select}
            value={selectedRegion ?? ""}
            onChange={(event) => applyRegion(event.target.value || undefined)}
          >
            <option value="">All regions</option>
            {mockDashboardRegions.map(({ region }) => (
              <option key={region} value={region}>
                {region}
              </option>
            ))}
          </select>
        </label>
        {selectedRegion ? (
          <>
            <span className={styles.filterChip}>region = {selectedRegion}</span>
            {!isDrilled ? (
              <button
                className={styles.actionButton}
                onClick={drillIntoCustomers}
              >
                Drill into customers
              </button>
            ) : (
              <button
                className={styles.actionButton}
                onClick={() => setDrillPath([])}
              >
                ← Back to regions
              </button>
            )}
            <button
              className={styles.clearButton}
              onClick={() => applyRegion()}
            >
              Clear
            </button>
          </>
        ) : null}
      </div>

      {isDrilled ? (
        <div className={styles.breadcrumb}>
          All regions / {selectedRegion} / Customers
        </div>
      ) : null}

      <div className={styles.gridShell}>
        <ResponsiveGridLayout
          className={styles.grid}
          layouts={layouts}
          breakpoints={{ lg: 1200, md: 996, sm: 0 }}
          cols={{ lg: 24, md: 20, sm: 12 }}
          rowHeight={24}
          margin={[12, 12]}
          isDraggable={false}
          isResizable={false}
          useCSSTransforms={false}
        >
          {spec.tiles.map((tile) => {
            const chart = spec.charts.find(({ id }) => id === tile.chartId);
            if (!chart || chart.visualization.type !== "cartesian") return null;
            const result = results[tile.uuid];
            const expectedDimension = isDrilled ? "customer" : "region";
            const readyResult = result?.columns.some(
              ({ name }) => name === expectedDimension,
            )
              ? result
              : undefined;
            const effectiveChart: ChartDefinition = isDrilled
              ? {
                  ...chart,
                  visualization: {
                    ...chart.visualization,
                    config: {
                      ...chart.visualization.config,
                      layout: {
                        ...chart.visualization.config.layout,
                        xField: "customer",
                      },
                    },
                  },
                }
              : chart;
            return (
              <section key={tile.uuid} className={styles.tile}>
                <header className={styles.tileHeader}>
                  <h2 className={styles.tileTitle}>{chart.title}</h2>
                  <p className={styles.tileDescription}>
                    {isDrilled
                      ? `Customers in ${selectedRegion}`
                      : chart.description}
                  </p>
                </header>
                <div className={styles.chart}>
                  {error ? <div className={styles.state}>{error}</div> : null}
                  {!error && !readyResult ? (
                    <div className={styles.state}>Loading…</div>
                  ) : null}
                  {readyResult ? (
                    <DashboardRenderer
                      chart={effectiveChart}
                      result={readyResult}
                      onMarkClick={(mark) =>
                        handleMarkClick(tile, chart, readyResult, mark)
                      }
                    />
                  ) : null}
                </div>
              </section>
            );
          })}
        </ResponsiveGridLayout>
      </div>

      <section className={styles.tableCard}>
        <div className={styles.tableHeader}>
          <div>
            <div className={styles.contextTitle}>Expandable rows</div>
            <h2 className={styles.tileTitle}>Region detail</h2>
          </div>
          <span className={styles.tableHint}>
            Click a row to expand customers
          </span>
        </div>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Region</th>
              <th>Revenue</th>
              <th>Customers</th>
            </tr>
          </thead>
          <tbody>
            {mockDashboardRegions
              .filter(
                ({ region }) => !selectedRegion || region === selectedRegion,
              )
              .flatMap(({ region, revenue, customers }) => {
                const expanded = expandedRegions.includes(region);
                return [
                  <tr
                    key={region}
                    className={styles.parentRow}
                    onClick={() =>
                      setExpandedRegions((current) =>
                        current.includes(region)
                          ? current.filter((item) => item !== region)
                          : [...current, region],
                      )
                    }
                  >
                    <td>
                      <span className={styles.chevron}>
                        {expanded ? "▾" : "▸"}
                      </span>
                      {region}
                    </td>
                    <td>${revenue.toLocaleString()}</td>
                    <td>{customers.length}</td>
                  </tr>,
                  ...(expanded
                    ? customers.map((customer) => (
                        <tr
                          key={`${region}-${customer.customer}`}
                          className={styles.childRow}
                        >
                          <td>{customer.customer}</td>
                          <td>${customer.revenue.toLocaleString()}</td>
                          <td>Customer</td>
                        </tr>
                      ))
                    : []),
                ];
              })}
          </tbody>
        </table>
      </section>

      <section className={styles.context} aria-live="polite">
        <div className={styles.contextTitle}>Normalized chart reference</div>
        <pre data-testid="dashboard-chart-reference">
          {reference
            ? JSON.stringify(reference, null, 2)
            : "Click a bar to filter every tile."}
        </pre>
      </section>
    </div>
  );
}
