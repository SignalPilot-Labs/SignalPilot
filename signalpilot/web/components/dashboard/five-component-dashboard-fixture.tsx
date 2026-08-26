"use client";

import type {
  DashboardDefinition,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";

import { DashboardRenderer } from "./dashboard-renderer";
import styles from "./dashboard-prototype.module.css";

const resultsByChartId: Record<string, DashboardQueryResult> = {
  "chart-kpi": {
    resultId: "fixture-result-kpi",
    executionId: "fixture-execution-kpi",
    columns: [
      {
        name: "orders.revenue",
        logicalType: "number",
        nullable: false,
        label: "Revenue",
      },
    ],
    rows: [{ "orders.revenue": 1_595_000 }],
    completeness: "complete",
    freshnessAt: "2026-08-24T12:00:00Z",
    timezone: "UTC",
    locale: "en-US",
  },
  "chart-table": {
    resultId: "fixture-result-table",
    executionId: "fixture-execution-table",
    columns: [
      {
        name: "orders.region",
        logicalType: "string",
        nullable: false,
        label: "Region",
      },
      {
        name: "orders.revenue",
        logicalType: "number",
        nullable: false,
        label: "Revenue",
      },
    ],
    rows: [
      { "orders.region": "Northeast", "orders.revenue": 520_000 },
      { "orders.region": "Southeast", "orders.revenue": 410_000 },
      { "orders.region": "West", "orders.revenue": 375_000 },
      { "orders.region": "Midwest", "orders.revenue": 290_000 },
    ],
    completeness: "complete",
    freshnessAt: "2026-08-24T12:00:00Z",
    timezone: "UTC",
    locale: "en-US",
  },
  "chart-bar": chartResult("bar", "orders.region", [
    ["Northeast", 520_000],
    ["Southeast", 410_000],
    ["West", 375_000],
    ["Midwest", 290_000],
  ]),
  "chart-line": chartResult("line", "orders.month", [
    ["2026-01", 360_000],
    ["2026-02", 385_000],
    ["2026-03", 410_000],
    ["2026-04", 440_000],
  ]),
  "chart-area": chartResult("area", "orders.month", [
    ["2026-01", 360_000],
    ["2026-02", 745_000],
    ["2026-03", 1_155_000],
    ["2026-04", 1_595_000],
  ]),
};

function chartResult(
  id: string,
  dimension: string,
  values: Array<[string, number]>,
): DashboardQueryResult {
  return {
    resultId: `fixture-result-${id}`,
    executionId: `fixture-execution-${id}`,
    columns: [
      {
        name: dimension,
        logicalType: "string",
        nullable: false,
        label: dimension === "orders.region" ? "Region" : "Month",
      },
      {
        name: "orders.revenue",
        logicalType: "number",
        nullable: false,
        label: "Revenue",
      },
    ],
    rows: values.map(([label, revenue]) => ({
      [dimension]: label,
      "orders.revenue": revenue,
    })),
    completeness: "complete",
    freshnessAt: "2026-08-24T12:00:00Z",
    timezone: "UTC",
    locale: "en-US",
  };
}

export function FiveComponentDashboardFixture({
  definition,
}: {
  definition: DashboardDefinition;
}) {
  return (
    <main className={styles.page} data-testid="five-component-dashboard">
      <div className={styles.header}>
        <div>
          <div className={styles.eyebrow}>Phase 1 renderer smoke fixture</div>
          <h1 className={styles.title}>{definition.name}</h1>
          <p className={styles.description}>
            KPI, table, bar, line, and area rendered from one engine-neutral
            dashboard definition.
          </p>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: 12,
        }}
      >
        {definition.tiles.map((tile) => {
          const chart = definition.charts.find(({ id }) => id === tile.chartId);
          if (!chart) throw new Error(`Missing chart '${tile.chartId}'`);
          const result = resultsByChartId[chart.id];
          if (!result) throw new Error(`Missing fixture result '${chart.id}'`);

          return (
            <section
              key={tile.uuid}
              className={styles.tile}
              data-testid={`fixture-tile-${chart.id}`}
            >
              <header className={styles.tileHeader}>
                <h2 className={styles.tileTitle}>{chart.title}</h2>
              </header>
              <div className={styles.chart} style={{ minHeight: 260 }}>
                <DashboardRenderer chart={chart} result={result} />
              </div>
            </section>
          );
        })}
      </div>
    </main>
  );
}
