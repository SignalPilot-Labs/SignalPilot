"use client";

import { useState } from "react";
import { createPortal } from "react-dom";

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
  loading,
  unaffectedFilters = 0,
  onMarkClick,
  onDrill,
  canDrill,
  drillSelection,
  drillContext,
  onDrillUp,
  onExpandRow,
}: {
  chart: ChartDefinition;
  result?: DashboardQueryResult;
  error?: string;
  loading?: boolean;
  unaffectedFilters?: number;
  onMarkClick?: (mark: Record<string, unknown>, multiselect: boolean) => void;
  onDrill?: () => void;
  canDrill?: boolean;
  drillSelection?: string;
  drillContext?: string;
  onDrillUp?: () => void;
  onExpandRow?: (row: Record<string, unknown>) => Promise<DashboardQueryResult>;
}) {
  const [showData, setShowData] = useState(false);
  return (
    <section className={styles.tile}>
      <header className={styles.tileHeader}>
        <h2>{chart.title}</h2>
        {chart.description ? <p>{chart.description}</p> : null}
      </header>
      <div className={styles.visual}>
        {error ? (
          <div className={styles.errorState}>Tile failed: {error}</div>
        ) : null}
        {loading && result ? (
          <div className={styles.refreshState}>Refreshing…</div>
        ) : null}
        {!error && loading && !result ? (
          <div className={styles.state}>Loading governed data…</div>
        ) : null}
        {!loading && !error && result?.rows.length === 0 ? (
          <div className={styles.state}>No data for this state.</div>
        ) : null}
        {result?.rows.length ? (
          <DashboardRenderer
            chart={chart}
            result={result}
            onMarkClick={onMarkClick}
            onExpandRow={onExpandRow}
          />
        ) : null}
      </div>
      {result ? (
        <footer className={styles.receiptSummary}>
          <span>
            {result.completeness}
            {result.completeness !== "complete"
              ? " — result may be incomplete"
              : ""}
          </span>
          <span>result {new Date(result.freshnessAt).toLocaleString()}</span>
          {result.cacheState === "stale" ? <span>Stale result</span> : null}
          {unaffectedFilters ? (
            <span>
              {unaffectedFilters} filter{unaffectedFilters === 1 ? "" : "s"} not
              mapped
            </span>
          ) : null}
        </footer>
      ) : null}
      <div className={styles.tileActions}>
        <button
          type="button"
          disabled={!result}
          onClick={() => setShowData(true)}
        >
          View data
        </button>
        {onDrill ? (
          <button
            type="button"
            disabled={!canDrill}
            title={
              canDrill
                ? `Drill into ${drillSelection}`
                : "Select a chart mark before drilling down"
            }
            onClick={onDrill}
          >
            Drill down
          </button>
        ) : null}
        {onDrillUp ? (
          <button type="button" onClick={onDrillUp}>
            Drill up
          </button>
        ) : null}
        {drillContext ? (
          <span className={styles.drillContext}>{drillContext}</span>
        ) : onDrill ? (
          <span className={styles.drillContext}>
            {drillSelection
              ? `Selected: ${drillSelection}`
              : "Select a chart mark to drill"}
          </span>
        ) : null}
      </div>
      {showData && result
        ? createPortal(
            <div
              className={styles.dataDialog}
              onClick={() => setShowData(false)}
              role="dialog"
              aria-modal="true"
              aria-label={`${chart.title} data`}
            >
              <section
                className={styles.dataDialogPanel}
                onClick={(event) => event.stopPropagation()}
              >
                <div>
                  <h3>{chart.title} · exact aggregated result</h3>
                  <button type="button" onClick={() => setShowData(false)}>
                    Close
                  </button>
                </div>
                <table>
                  <thead>
                    <tr>
                      {result.columns.map((column) => (
                        <th key={column.name}>{column.label ?? column.name}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, index) => (
                      <tr key={index}>
                        {result.columns.map((column) => (
                          <td key={column.name}>
                            {String(row[column.name] ?? "—")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            </div>,
            document.body,
          )
        : null}
    </section>
  );
}
