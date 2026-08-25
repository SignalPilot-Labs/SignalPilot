"use client";

import { RefreshCw } from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { DashboardChartTile } from "~/components/dashboard/dashboard-chart-tile";
import { DashboardAnalysisDialog } from "~/components/dashboard/dashboard-analysis-dialog";
import { DashboardControlBar } from "~/components/dashboard/dashboard-control-bar";
import { DashboardDetailsDrawer } from "~/components/dashboard/dashboard-inspector";
import {
  DashboardApiDataSource,
  isUnsafeTruncatedSeriesError,
  type DashboardQueryReceipt,
} from "~/lib/dashboard/api-data-source";
import type {
  ChartDefinition,
  DashboardDefinition,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";
import {
  initialDashboardRuntimeState,
  markRemainsSelected,
  parseDashboardRuntimeState,
  chartForAvailableResult,
  runtimeStateSearchParams,
  toggleCrossFilter,
} from "~/lib/dashboard/runtime-state";
import {
  fieldLabel,
  formatDashboardTimestamp,
  formatDashboardValue,
  viewerLocale,
} from "~/lib/dashboard/semantic-formatter";
import {
  normalizedTileSpan,
  orderDashboardTiles,
} from "~/lib/dashboard/dashboard-layout";

import styles from "./dashboard-runtime.module.css";

function hierarchyFor(chart: ChartDefinition): string[] {
  if (chart.query.kind !== "semantic") return [];
  const base = chart.query.dimensions.slice(-1);
  const configured =
    chart.signalPilot.drillDimensions ?? chart.signalPilot.tableGroups ?? [];
  return [...base, ...configured.filter((field) => !base.includes(field))];
}

function isRuntimeScalar(value: unknown): value is string | number | boolean {
  return ["string", "number", "boolean"].includes(typeof value);
}

export function DashboardRuntimeProvider({
  dashboardId,
  versionId,
  definition,
  authoringSessionId,
  onVisibleReceiptsChange,
  onRuntimeFiltersChange,
  onRuntimeDrillsChange,
  analysisEnabled = true,
  lifecycleActions,
  lifecycleNotice,
}: {
  dashboardId: string;
  versionId: string;
  definition: DashboardDefinition;
  authoringSessionId?: string;
  onVisibleReceiptsChange?: (
    receipts: Record<string, DashboardQueryReceipt>,
  ) => void;
  onRuntimeFiltersChange?: (
    filters: ReturnType<typeof initialDashboardRuntimeState>["filters"],
  ) => void;
  onRuntimeDrillsChange?: (
    drills: ReturnType<typeof initialDashboardRuntimeState>["drills"],
  ) => void;
  analysisEnabled?: boolean;
  lifecycleActions?: ReactNode;
  lifecycleNotice?: ReactNode;
}) {
  const [runtimeState, setRuntimeState] = useState(() =>
    typeof window === "undefined"
      ? initialDashboardRuntimeState(definition)
      : parseDashboardRuntimeState(definition, window.location.search),
  );
  const [results, setResults] = useState<Record<string, DashboardQueryResult>>(
    {},
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [receipts, setReceipts] = useState<
    Record<string, DashboardQueryReceipt>
  >({});
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const handledRefresh = useRef(0);
  const refreshPending = useRef(false);
  const refreshedStaleKeys = useRef(new Set<string>());
  const [detailsChartId, setDetailsChartId] = useState<string>();
  const [selectedMarks, setSelectedMarks] = useState<
    Record<string, Record<string, unknown>>
  >({});
  const [analysisChartId, setAnalysisChartId] = useState<string>();
  const previousDefinition = useRef(definition);
  const dataSource = useMemo(
    () =>
      new DashboardApiDataSource(
        dashboardId,
        versionId,
        (chart, receipt) =>
          setReceipts((current) => ({ ...current, [chart.id]: receipt })),
        authoringSessionId,
        definition.signalPilot.timezone,
        viewerLocale(),
      ),
    [
      authoringSessionId,
      dashboardId,
      definition.signalPilot.timezone,
      versionId,
    ],
  );
  const layoutTiles = useMemo(
    () => orderDashboardTiles(definition.tiles),
    [definition.tiles],
  );

  useEffect(() => {
    if (previousDefinition.current === definition) return;
    previousDefinition.current = definition;
    setRuntimeState(initialDashboardRuntimeState(definition));
    setResults({});
    setErrors({});
    setReceipts({});
    setSelectedMarks({});
    setDetailsChartId(undefined);
  }, [definition]);

  useEffect(() => {
    onVisibleReceiptsChange?.(receipts);
  }, [onVisibleReceiptsChange, receipts]);

  useEffect(() => {
    onRuntimeFiltersChange?.(runtimeState.filters);
  }, [onRuntimeFiltersChange, runtimeState.filters]);

  useEffect(() => {
    onRuntimeDrillsChange?.(runtimeState.drills);
  }, [onRuntimeDrillsChange, runtimeState.drills]);

  useEffect(() => {
    const next = runtimeStateSearchParams(definition, runtimeState);
    const url = new URL(window.location.href);
    url.searchParams.delete("filters");
    url.searchParams.delete("drillPath");
    new URLSearchParams(next.toString()).forEach((value, key) =>
      url.searchParams.set(key, value),
    );
    window.history.replaceState(null, "", url);
  }, [definition, runtimeState]);

  useEffect(() => {
    const controller = new AbortController();
    let pendingTiles = 0;
    const invalidateCache = refreshGeneration > handledRefresh.current;
    handledRefresh.current = refreshGeneration;
    for (const tile of definition.tiles) {
      const chart = definition.charts.find((item) => item.id === tile.chartId);
      if (!chart) continue;
      pendingTiles += 1;
      setLoading((current) => ({ ...current, [chart.id]: true }));
      setErrors((current) => {
        const next = { ...current };
        delete next[chart.id];
        return next;
      });
      void dataSource
        .loadTile(
          tile,
          chart,
          {
            filters: [],
            drillPath: [],
            dashboardFilters: runtimeState.filters,
            dashboardDrillPath: runtimeState.drills[chart.id] ?? [],
            invalidateCache,
          },
          controller.signal,
        )
        .then((result) =>
          setResults((current) => ({ ...current, [chart.id]: result })),
        )
        .catch((cause) => {
          if (controller.signal.aborted) return;
          if (isUnsafeTruncatedSeriesError(cause)) {
            setResults((current) => {
              const next = { ...current };
              delete next[chart.id];
              return next;
            });
            setReceipts((current) => {
              const next = { ...current };
              delete next[chart.id];
              return next;
            });
          }
          setErrors((current) => ({
            ...current,
            [chart.id]: cause instanceof Error ? cause.message : "Query failed",
          }));
        })
        .finally(() => {
          pendingTiles -= 1;
          if (!controller.signal.aborted) {
            setLoading((current) => ({ ...current, [chart.id]: false }));
            if (pendingTiles === 0) refreshPending.current = false;
          }
        });
    }
    return () => controller.abort();
  }, [
    dataSource,
    definition.charts,
    definition.tiles,
    refreshGeneration,
    runtimeState,
  ]);

  useEffect(() => {
    if (Object.values(loading).some(Boolean)) return;
    const stale = Object.values(receipts).find(
      (receipt) => receipt.cache_state === "stale",
    );
    if (!stale || refreshedStaleKeys.current.has(stale.dashboard_result_id))
      return;
    refreshedStaleKeys.current.add(stale.dashboard_result_id);
    refreshPending.current = true;
    setRefreshGeneration((value) => value + 1);
  }, [loading, receipts]);

  const reset = () => {
    setRuntimeState(initialDashboardRuntimeState(definition));
    setSelectedMarks({});
  };
  const dashboardLoading = Object.values(loading).some(Boolean);
  const hasVisibleResults = Object.keys(results).length > 0;
  const formatContext = {
    locale: viewerLocale(),
    timezone: definition.signalPilot.timezone,
  };
  const dashboardFreshnessAt = Object.values(results)
    .map((result) => result.freshnessAt)
    .filter((value) => !Number.isNaN(new Date(value).valueOf()))
    .sort((left, right) => new Date(left).valueOf() - new Date(right).valueOf())
    .at(0);
  const refreshHelp = dashboardFreshnessAt
    ? `Data as of ${formatDashboardTimestamp(dashboardFreshnessAt, formatContext)}. Automatically refreshes when data is more than 5 minutes old.`
    : "Refresh dashboard. Automatically refreshes when data is more than 5 minutes old.";
  const refreshDashboard = () => {
    if (dashboardLoading || refreshPending.current) return;
    refreshPending.current = true;
    setRefreshGeneration((value) => value + 1);
  };

  return (
    <div className={styles.runtime} data-dashboard-export-root>
      <main>
        <header className={styles.header}>
          <div>
            <h1>{definition.name}</h1>
            <p>{definition.description}</p>
          </div>
          <div className={styles.headerActions}>
            {dashboardLoading || Object.keys(errors).length ? (
              <span
                className={styles.dashboardRefreshState}
                role="status"
                data-dashboard-export-exclude
              >
                {dashboardLoading
                  ? hasVisibleResults
                    ? "Refreshing dashboard…"
                    : "Loading dashboard…"
                  : "Some charts need attention"}
              </span>
            ) : null}
            {lifecycleActions ? (
              <div data-dashboard-export-exclude>{lifecycleActions}</div>
            ) : null}
            <div
              className={styles.refreshButtonWrap}
              data-dashboard-export-exclude
            >
              <button
                type="button"
                disabled={dashboardLoading}
                onClick={refreshDashboard}
                aria-label={
                  dashboardLoading && hasVisibleResults
                    ? "Refreshing dashboard"
                    : "Refresh dashboard"
                }
                aria-describedby="dashboard-refresh-help"
              >
                <RefreshCw size={17} aria-hidden="true" />
              </button>
              <span
                className={styles.refreshTooltip}
                id="dashboard-refresh-help"
                role="tooltip"
              >
                {refreshHelp}
              </span>
            </div>
          </div>
        </header>
        {lifecycleNotice}
        <DashboardControlBar
          dashboardId={dashboardId}
          versionId={versionId}
          definition={definition}
          filters={runtimeState.filters}
          onChange={(filters) => {
            setSelectedMarks({});
            setRuntimeState((current) => ({ ...current, filters }));
          }}
          onReset={reset}
        />
        <div className={styles.grid}>
          {layoutTiles.map((tile) => {
            const chart = definition.charts.find(
              (item) => item.id === tile.chartId,
            );
            if (!chart) return null;
            const rowTiles = layoutTiles.filter(
              (candidate) => candidate.y === tile.y,
            );
            const compactRow = rowTiles.every((candidate) =>
              definition.charts.some(
                (candidateChart) =>
                  candidateChart.id === candidate.chartId &&
                  candidateChart.visualization.type === "big_number",
              ),
            );
            const drillPath = runtimeState.drills[chart.id] ?? [];
            const hierarchy = hierarchyFor(chart);
            const activeDimension = hierarchy[drillPath.length];
            const selectedMark = selectedMarks[chart.id];
            const result = results[chart.id];
            const savedFilter = definition.filters.dimensions.find(
              (rule) => rule.target.fieldId === activeDimension,
            );
            const selectedValue = selectedMark?.[activeDimension];
            const supportsButtonDrill =
              chart.visualization.type === "cartesian" && hierarchy.length > 1;
            const unaffectedFilters = runtimeState.filters.filter((filter) => {
              const saved = definition.filters.dimensions.find(
                (rule) => rule.id === filter.id,
              );
              if (!saved) return true;
              const explicit = saved.tileTargets?.[tile.uuid];
              if (explicit === false) return true;
              return (
                explicit === undefined &&
                (chart.query.kind !== "semantic" ||
                  saved.target.tableName !== chart.query.exploreName)
              );
            }).length;
            const canExpand =
              chart.visualization.type === "table" && hierarchy.length > 1;
            return (
              <div
                className={styles.tileButton}
                key={tile.uuid}
                style={
                  {
                    gridColumn: `span ${normalizedTileSpan(tile, rowTiles)}`,
                    "--dashboard-tile-height": compactRow ? "260px" : "380px",
                  } as CSSProperties
                }
              >
                <DashboardChartTile
                  chart={chartForAvailableResult(chart, result)}
                  result={result}
                  error={errors[chart.id]}
                  loading={loading[chart.id]}
                  unaffectedFilters={unaffectedFilters}
                  onMarkSelect={(mark) =>
                    setSelectedMarks((current) => ({
                      ...current,
                      [chart.id]: mark,
                    }))
                  }
                  selectionLabel={
                    isRuntimeScalar(selectedValue)
                      ? formatDashboardValue(
                          selectedValue,
                          result?.columns.find(
                            (column) => column.name === activeDimension,
                          ),
                          result,
                        )
                      : undefined
                  }
                  onFilter={
                    chart.signalPilot.crossFilter && savedFilter
                      ? () => {
                          if (!isRuntimeScalar(selectedValue)) return;
                          const nextFilters = toggleCrossFilter(
                            runtimeState.filters,
                            savedFilter,
                            selectedValue,
                            false,
                          );
                          setRuntimeState((current) => ({
                            ...current,
                            filters: nextFilters,
                          }));
                          if (
                            !markRemainsSelected(
                              nextFilters,
                              savedFilter.id,
                              selectedMark,
                              activeDimension,
                            )
                          ) {
                            setSelectedMarks((current) => {
                              const next = { ...current };
                              delete next[chart.id];
                              return next;
                            });
                          }
                        }
                      : undefined
                  }
                  canFilter={isRuntimeScalar(selectedValue)}
                  onDrill={
                    supportsButtonDrill
                      ? () => {
                          if (!isRuntimeScalar(selectedValue)) return;
                          setRuntimeState((current) => ({
                            ...current,
                            drills: {
                              ...current.drills,
                              [chart.id]: [
                                ...(current.drills[chart.id] ?? []),
                                {
                                  fieldId: activeDimension,
                                  value: selectedValue,
                                },
                              ],
                            },
                          }));
                        }
                      : undefined
                  }
                  canDrill={
                    isRuntimeScalar(selectedValue) &&
                    drillPath.length < hierarchy.length - 1
                  }
                  drillBreadcrumb={drillPath.map((step) => ({
                    label: fieldLabel(step.fieldId),
                    value: String(step.value),
                  }))}
                  onDrillTo={(depth) =>
                    setRuntimeState((current) => ({
                      ...current,
                      drills: {
                        ...current.drills,
                        [chart.id]: drillPath.slice(0, depth),
                      },
                    }))
                  }
                  onExpandRow={
                    canExpand
                      ? async (row) => {
                          const value = row[hierarchy[0]];
                          if (!isRuntimeScalar(value))
                            throw new Error(
                              "Expandable group value is unavailable",
                            );
                          return dataSource.loadTile(
                            tile,
                            chart,
                            {
                              filters: [],
                              drillPath: [],
                              dashboardFilters: runtimeState.filters,
                              dashboardDrillPath: [
                                { fieldId: hierarchy[0], value },
                              ],
                            },
                            new AbortController().signal,
                          );
                        }
                      : undefined
                  }
                  onAnalyze={
                    analysisEnabled && result && receipts[chart.id]
                      ? () => setAnalysisChartId(chart.id)
                      : undefined
                  }
                  onDetails={() => setDetailsChartId(chart.id)}
                />
              </div>
            );
          })}
        </div>
      </main>
      {detailsChartId
        ? (() => {
            const chart = definition.charts.find(
              (item) => item.id === detailsChartId,
            );
            if (!chart) return null;
            return (
              <DashboardDetailsDrawer
                chart={chart}
                result={results[chart.id]}
                receipt={receipts[chart.id]}
                filters={runtimeState.filters}
                onClose={() => setDetailsChartId(undefined)}
              />
            );
          })()
        : null}
      {analysisChartId
        ? (() => {
            const chart = definition.charts.find(
              (item) => item.id === analysisChartId,
            );
            const tile = definition.tiles.find(
              (item) => item.chartId === analysisChartId,
            );
            const result = results[analysisChartId];
            const receipt = receipts[analysisChartId];
            if (!chart || !tile || !result || !receipt) return null;
            return (
              <DashboardAnalysisDialog
                dashboardId={dashboardId}
                versionId={versionId}
                tileUuid={tile.uuid}
                chart={chartForAvailableResult(chart, result)}
                result={result}
                dashboardResultId={receipt.dashboard_result_id}
                filters={runtimeState.filters}
                drillPath={runtimeState.drills[chart.id] ?? []}
                selectedMark={selectedMarks[chart.id] ?? {}}
                onClose={() => setAnalysisChartId(undefined)}
              />
            );
          })()
        : null}
    </div>
  );
}
