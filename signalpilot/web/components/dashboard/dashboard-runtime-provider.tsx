"use client";

import { useEffect, useMemo, useState } from "react";

import { DashboardChartTile } from "~/components/dashboard/dashboard-chart-tile";
import { DashboardInspector } from "~/components/dashboard/dashboard-inspector";
import {
  DashboardApiDataSource,
  type DashboardQueryReceipt,
} from "~/lib/dashboard/api-data-source";
import type {
  DashboardDefinition,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";

import styles from "./dashboard-runtime.module.css";

export function DashboardRuntimeProvider({
  dashboardId,
  versionId,
  definition,
}: {
  dashboardId: string;
  versionId: string;
  definition: DashboardDefinition;
}) {
  const [results, setResults] = useState<Record<string, DashboardQueryResult>>(
    {},
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [receipts, setReceipts] = useState<
    Record<string, DashboardQueryReceipt>
  >({});
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const [selectedChartId, setSelectedChartId] = useState(
    definition.charts[0]?.id,
  );
  const dataSource = useMemo(
    () =>
      new DashboardApiDataSource(
        dashboardId,
        versionId,
        refreshGeneration > 0,
        (chart, receipt) =>
          setReceipts((current) => ({ ...current, [chart.id]: receipt })),
      ),
    [dashboardId, refreshGeneration, versionId],
  );

  useEffect(() => {
    const controller = new AbortController();
    definition.tiles.forEach((tile) => {
      const chart = definition.charts.find((item) => item.id === tile.chartId);
      if (!chart) return;
      dataSource
        .loadTile(
          tile,
          chart,
          { filters: [], drillPath: [] },
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
        });
    });
    return () => controller.abort();
  }, [dataSource, definition.charts, definition.tiles]);

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
        <div className={styles.grid}>
          {definition.tiles.map((tile) => {
            const chart = definition.charts.find(
              (item) => item.id === tile.chartId,
            );
            if (!chart) return null;
            return (
              <button
                className={styles.tileButton}
                key={tile.uuid}
                onClick={() => setSelectedChartId(chart.id)}
              >
                <DashboardChartTile
                  chart={chart}
                  result={results[chart.id]}
                  error={errors[chart.id]}
                />
              </button>
            );
          })}
        </div>
      </main>
      <DashboardInspector
        receipt={selectedChartId ? receipts[selectedChartId] : undefined}
      />
    </div>
  );
}
