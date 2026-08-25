"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { DashboardRenderer } from "~/components/dashboard/dashboard-renderer";
import { DashboardLoadingState } from "~/components/dashboard/dashboard-loading-state";
import { DashboardConfidenceFlag } from "~/components/dashboard/dashboard-confidence-flag";
import type {
  ChartDefinition,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";
import {
  fieldLabel,
  formatDashboardCell,
  formatDashboardTimestamp,
} from "~/lib/dashboard/semantic-formatter";

import styles from "./dashboard-runtime.module.css";

function displayErrorMessage(error: string): string {
  if (error.includes("dashboard_time_series_truncated")) {
    return "This time series exceeds its safe row limit. Narrow the date range or update the dashboard limit before using it.";
  }
  return /failed to fetch|networkerror|500:\s*internal server error/i.test(
    error,
  )
    ? "The data source is temporarily unavailable. Try refreshing in a moment."
    : error;
}

function ResultDialog({
  chart,
  result,
  onClose,
}: {
  chart: ChartDefinition;
  result: DashboardQueryResult;
  onClose: () => void;
}) {
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeButton.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return createPortal(
    <div
      className={styles.dataDialog}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby={`data-dialog-${chart.id}`}
    >
      <section className={styles.dataDialogPanel}>
        <header className={styles.dataDialogHeader}>
          <div>
            <span>Exact aggregated result</span>
            <h3 id={`data-dialog-${chart.id}`}>{chart.title}</h3>
            <p>
              {result.rows.length.toLocaleString(result.locale)} visible rows
            </p>
          </div>
          <button ref={closeButton} type="button" onClick={onClose}>
            Close
          </button>
        </header>
        <div
          className={styles.dataTableViewport}
          tabIndex={0}
          aria-label={`${chart.title} result table`}
        >
          <table>
            <thead>
              <tr>
                {result.columns.map((column) => (
                  <th key={column.name} scope="col">
                    {column.label ?? fieldLabel(column.name)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, index) => (
                <tr key={index}>
                  {result.columns.map((column) => (
                    <td key={column.name}>
                      {formatDashboardCell(row[column.name], column, result)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>,
    document.body,
  );
}

export function DashboardChartTile({
  chart,
  result,
  error,
  loading,
  unaffectedFilters = 0,
  onMarkSelect,
  selectionLabel,
  onFilter,
  canFilter,
  onDrill,
  canDrill,
  drillBreadcrumb = [],
  onDrillTo,
  onExpandRow,
  onAnalyze,
  onDetails,
}: {
  chart: ChartDefinition;
  result?: DashboardQueryResult;
  error?: string;
  loading?: boolean;
  unaffectedFilters?: number;
  onMarkSelect?: (mark: Record<string, unknown>) => void;
  selectionLabel?: string;
  onFilter?: () => void;
  canFilter?: boolean;
  onDrill?: () => void;
  canDrill?: boolean;
  drillBreadcrumb?: Array<{ label: string; value: string }>;
  onDrillTo?: (depth: number) => void;
  onExpandRow?: (row: Record<string, unknown>) => Promise<DashboardQueryResult>;
  onAnalyze?: () => void;
  onDetails?: () => void;
}) {
  const [showData, setShowData] = useState(false);
  const isKpi = chart.visualization.type === "big_number";
  const question =
    chart.question ??
    (isKpi ? `What is our ${chart.title.toLowerCase()}?` : chart.title);
  return (
    <section
      className={`${styles.tile} ${isKpi ? styles.kpiTile : styles.chartTile}`}
      aria-busy={loading}
    >
      <header className={styles.tileHeader}>
        <div className={styles.questionWrap}>
          <h2 tabIndex={chart.description ? 0 : undefined}>{question}</h2>
          {chart.description ? (
            <div className={styles.questionTooltip} role="tooltip">
              {chart.description}
            </div>
          ) : null}
        </div>
        <DashboardConfidenceFlag chart={chart} />
        <details className={styles.tileMenu}>
          <summary aria-label={`More actions for ${chart.title}`}>•••</summary>
          <div className={styles.tileMenuPanel}>
            {result ? (
              <div className={styles.tileMenuMeta}>
                <span>
                  {result.completeness === "complete"
                    ? "Complete result"
                    : "Result may be incomplete"}
                </span>
                <span>
                  Updated {formatDashboardTimestamp(result.freshnessAt, result)}
                </span>
                {result.cacheState === "stale" ? (
                  <span>Updating cached result</span>
                ) : null}
                {unaffectedFilters ? (
                  <span>
                    {unaffectedFilters} unmapped filter
                    {unaffectedFilters === 1 ? "" : "s"}
                  </span>
                ) : null}
              </div>
            ) : null}
            <button
              type="button"
              disabled={!result}
              onClick={() => setShowData(true)}
            >
              View data
            </button>
            {onAnalyze ? (
              <button type="button" disabled={!result} onClick={onAnalyze}>
                Analyze this change
              </button>
            ) : null}
            {onDetails ? (
              <button type="button" onClick={onDetails}>
                Details
              </button>
            ) : null}
          </div>
        </details>
      </header>
      {drillBreadcrumb.length ? (
        <nav
          className={styles.drillBreadcrumb}
          aria-label={`${chart.title} drill path`}
        >
          <button type="button" onClick={() => onDrillTo?.(0)}>
            All
          </button>
          {drillBreadcrumb.map((step, index) => (
            <span key={`${step.label}-${index}`}>
              <span aria-hidden="true">/</span>
              <button type="button" onClick={() => onDrillTo?.(index + 1)}>
                {step.label}: {step.value}
              </button>
            </span>
          ))}
        </nav>
      ) : null}
      <div className={styles.visual}>
        {error ? (
          <div className={styles.errorState} role="status">
            {result
              ? "Latest refresh failed; showing the previous result. "
              : "This chart could not load. "}
            {displayErrorMessage(error)}
          </div>
        ) : null}
        {loading && !result ? (
          <DashboardLoadingState label="Loading governed data" hideLabel />
        ) : null}
        {!loading && !error && result?.rows.length === 0 ? (
          <div className={styles.state}>
            No data matches this dashboard state.
          </div>
        ) : null}
        {result?.rows.length ? (
          <DashboardRenderer
            chart={chart}
            result={result}
            onMarkClick={
              onMarkSelect ? (mark) => onMarkSelect(mark) : undefined
            }
            onExpandRow={onExpandRow}
          />
        ) : null}
      </div>
      {selectionLabel ? (
        <div
          className={styles.selectionActions}
          role="group"
          aria-label={`Actions for ${selectionLabel}`}
        >
          <span>Selected: {selectionLabel}</span>
          {onFilter ? (
            <button type="button" disabled={!canFilter} onClick={onFilter}>
              Filter dashboard
            </button>
          ) : null}
          {onDrill ? (
            <button type="button" disabled={!canDrill} onClick={onDrill}>
              Drill into value
            </button>
          ) : null}
        </div>
      ) : null}
      {showData && result ? (
        <ResultDialog
          chart={chart}
          result={result}
          onClose={() => setShowData(false)}
        />
      ) : null}
    </section>
  );
}
