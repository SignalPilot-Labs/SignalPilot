"use client";

import { useEffect, useRef } from "react";

import type { DashboardQueryReceipt } from "~/lib/dashboard/api-data-source";
import { dashboardDialectLabel } from "~/lib/dashboard/dialect-label";
import type {
  ChartDefinition,
  DashboardQueryResult,
  DashboardRuntimeFilter,
} from "~/lib/dashboard/contracts";
import {
  fieldLabel,
  formatDashboardTimestamp,
} from "~/lib/dashboard/semantic-formatter";

import styles from "./dashboard-runtime.module.css";

export function DashboardDetailsDrawer({
  chart,
  result,
  receipt,
  filters,
  onClose,
}: {
  chart: ChartDefinition;
  result?: DashboardQueryResult;
  receipt?: DashboardQueryReceipt;
  filters: DashboardRuntimeFilter[];
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
  const semantic = chart.query.kind === "semantic";
  const source =
    chart.query.kind === "semantic"
      ? fieldLabel(chart.query.exploreName)
      : "Confirmed custom query";
  return (
    <div
      className={styles.drawerBackdrop}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        className={styles.detailsDrawer}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`details-${chart.id}`}
      >
        <header>
          <div>
            <span>Chart details</span>
            <h2 id={`details-${chart.id}`}>{chart.title}</h2>
          </div>
          <button ref={closeButton} type="button" onClick={onClose}>
            Close
          </button>
        </header>
        <section>
          <h3>Business definition</h3>
          <p>
            {chart.description ??
              "No additional business definition was provided."}
          </p>
          <dl>
            <dt>Source</dt>
            <dd>{source}</dd>
            <dt>Active filters</dt>
            <dd>{filters.length ? `${filters.length} applied` : "None"}</dd>
            <dt>Freshness</dt>
            <dd>
              {result
                ? formatDashboardTimestamp(result.freshnessAt, result)
                : "Not loaded"}
            </dd>
            <dt>Completeness</dt>
            <dd>{result?.completeness ?? "Unknown"}</dd>
            <dt>Confidence</dt>
            <dd>
              {semantic
                ? "High — governed semantic definition"
                : "Low — explicitly confirmed custom SQL"}
            </dd>
          </dl>
        </section>
        <details className={styles.technicalDetails}>
          <summary>Technical details</summary>
          {!receipt ? (
            <p>Query diagnostics are available after this chart loads.</p>
          ) : (
            <>
              <dl>
                <dt>Execution ID</dt>
                <dd>{receipt.execution_id}</dd>
                <dt>Result ID</dt>
                <dd>{receipt.dashboard_result_id}</dd>
                <dt>SQL hash</dt>
                <dd>{receipt.sql_hash}</dd>
                <dt>Parameter hash</dt>
                <dd>{receipt.parameter_hash}</dd>
              </dl>
              <details>
                <summary>Semantic definition</summary>
                <pre>
                  {JSON.stringify(receipt.semantic_definition, null, 2)}
                </pre>
              </details>
              {receipt.compiled_sql ? (
                <details>
                  <summary>
                    Compiled {dashboardDialectLabel(receipt.connection_type)}
                  </summary>
                  <pre>{receipt.compiled_sql}</pre>
                </details>
              ) : null}
            </>
          )}
        </details>
      </aside>
    </div>
  );
}
