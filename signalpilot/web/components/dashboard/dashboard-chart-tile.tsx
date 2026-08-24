"use client";

import { DashboardRenderer } from "~/components/dashboard/dashboard-renderer";
import type {
  ChartDefinition,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";

import styles from "./dashboard-runtime.module.css";

export function DashboardChartTile({
  chart,
  result,
  error,
}: {
  chart: ChartDefinition;
  result?: DashboardQueryResult;
  error?: string;
}) {
  return (
    <section className={styles.tile}>
      <header className={styles.tileHeader}>
        <h2>{chart.title}</h2>
        {chart.description ? <p>{chart.description}</p> : null}
      </header>
      <div className={styles.visual}>
        {error ? <div className={styles.state}>{error}</div> : null}
        {!error && !result ? (
          <div className={styles.state}>Loading governed data…</div>
        ) : null}
        {result ? <DashboardRenderer chart={chart} result={result} /> : null}
      </div>
      {result ? (
        <footer className={styles.receiptSummary}>
          <span>{result.completeness}</span>
          <span>result {new Date(result.freshnessAt).toLocaleString()}</span>
        </footer>
      ) : null}
    </section>
  );
}
