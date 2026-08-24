"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { DashboardChartTile } from "~/components/dashboard/dashboard-chart-tile";
import { DashboardAnalysisDialog } from "~/components/dashboard/dashboard-analysis-dialog";
import { DashboardControlBar } from "~/components/dashboard/dashboard-control-bar";
import { DashboardInspector } from "~/components/dashboard/dashboard-inspector";
import {
  DashboardApiDataSource,
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
  analysisEnabled = true,
}: {
  dashboardId: string;
  versionId: string;
  definition: DashboardDefinition;
  authoringSessionId?: string;
  onVisibleReceiptsChange?: (
    receipts: Record<string, DashboardQueryReceipt>,
  ) => void;
  analysisEnabled?: boolean;
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
  const refreshedStaleKeys = useRef(new Set<string>());
  const [selectedChartId, setSelectedChartId] = useState(
    definition.charts[0]?.id,
  );
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
      ),
    [authoringSessionId, dashboardId, versionId],
  );

  useEffect(() => {
    if (previousDefinition.current === definition) return;
    previousDefinition.current = definition;
    setRuntimeState(initialDashboardRuntimeState(definition));
    setResults({});
    setErrors({});
    setReceipts({});
    setSelectedMarks({});
    setSelectedChartId(definition.charts[0]?.id);
  }, [definition]);

  useEffect(() => {
    onVisibleReceiptsChange?.(receipts);
  }, [onVisibleReceiptsChange, receipts]);

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
    const invalidateCache = refreshGeneration > handledRefresh.current;
    handledRefresh.current = refreshGeneration;
    for (const tile of definition.tiles) {
      const chart = definition.charts.find((item) => item.id === tile.chartId);
      if (!chart) continue;
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
          setErrors((current) => ({
            ...current,
            [chart.id]: cause instanceof Error ? cause.message : "Query failed",
          }));
        })
        .finally(() => {
          if (!controller.signal.aborted)
            setLoading((current) => ({ ...current, [chart.id]: false }));
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
    const stale = Object.values(receipts).find(
      (receipt) => receipt.cache_state === "stale",
    );
    if (!stale || refreshedStaleKeys.current.has(stale.dashboard_result_id))
      return;
    refreshedStaleKeys.current.add(stale.dashboard_result_id);
    setRefreshGeneration((value) => value + 1);
  }, [receipts]);

  const reset = () => {
    setRuntimeState(initialDashboardRuntimeState(definition));
    setSelectedMarks({});
  };

  return (
    <div className={styles.runtime}>
      <main>
        <header className={styles.header}>
          <div>
            <span>Immutable version</span>
            <h1>{definition.name}</h1>
            <p>{definition.description}</p>
          </div>
          <div className={styles.headerActions}>
            <code>{versionId}</code>
            <button onClick={() => setRefreshGeneration((value) => value + 1)}>
              Refresh governed data
            </button>
          </div>
        </header>
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
          {definition.tiles.map((tile) => {
            const chart = definition.charts.find(
              (item) => item.id === tile.chartId,
            );
            if (!chart) return null;
            const drillPath = runtimeState.drills[chart.id] ?? [];
            const hierarchy = hierarchyFor(chart);
            const activeDimension = hierarchy[drillPath.length];
            const selectedMark = selectedMarks[chart.id];
            const result = results[chart.id];
            const savedFilter = definition.filters.dimensions.find(
              (rule) => rule.target.fieldId === activeDimension,
            );
            const selectedValue = selectedMark?.[activeDimension];
            const singletonValue =
              result?.rows.length === 1
                ? result.rows[0]?.[activeDimension]
                : undefined;
            const drillValue = isRuntimeScalar(selectedValue)
              ? selectedValue
              : isRuntimeScalar(singletonValue)
                ? singletonValue
                : undefined;
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
                onClick={() => setSelectedChartId(chart.id)}
              >
                <DashboardChartTile
                  chart={chartForAvailableResult(chart, result)}
                  result={result}
                  error={errors[chart.id]}
                  loading={loading[chart.id]}
                  unaffectedFilters={unaffectedFilters}
                  onMarkClick={
                    chart.signalPilot.crossFilter && savedFilter
                      ? (mark, multiselect) => {
                          const value = mark[activeDimension];
                          if (!isRuntimeScalar(value)) return;
                          const nextFilters = toggleCrossFilter(
                            runtimeState.filters,
                            savedFilter,
                            value,
                            multiselect,
                          );
                          const remainsSelected = markRemainsSelected(
                            nextFilters,
                            savedFilter.id,
                            mark,
                            activeDimension,
                          );
                          setSelectedMarks((current) => {
                            const next = { ...current };
                            if (remainsSelected) next[chart.id] = mark;
                            else delete next[chart.id];
                            return next;
                          });
                          setRuntimeState((current) => ({
                            ...current,
                            filters: nextFilters,
                          }));
                        }
                      : undefined
                  }
                  onDrill={
                    supportsButtonDrill
                      ? () => {
                          if (!isRuntimeScalar(drillValue)) return;
                          setRuntimeState((current) => ({
                            ...current,
                            drills: {
                              ...current.drills,
                              [chart.id]: [
                                ...(current.drills[chart.id] ?? []),
                                {
                                  fieldId: activeDimension,
                                  value: drillValue,
                                },
                              ],
                            },
                          }));
                        }
                      : undefined
                  }
                  canDrill={
                    isRuntimeScalar(drillValue) &&
                    drillPath.length < hierarchy.length - 1
                  }
                  drillSelection={
                    isRuntimeScalar(drillValue) ? String(drillValue) : undefined
                  }
                  drillContext={
                    drillPath.length
                      ? `Drilled: ${drillPath
                          .map(
                            (step) =>
                              `${step.fieldId.split(".").at(-1)} = ${step.value}`,
                          )
                          .join(" / ")}`
                      : undefined
                  }
                  onDrillUp={
                    supportsButtonDrill && drillPath.length
                      ? () =>
                          setRuntimeState((current) => ({
                            ...current,
                            drills: {
                              ...current.drills,
                              [chart.id]: drillPath.slice(0, -1),
                            },
                          }))
                      : undefined
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
                />
              </div>
            );
          })}
        </div>
      </main>
      <DashboardInspector
        receipt={selectedChartId ? receipts[selectedChartId] : undefined}
      />
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
