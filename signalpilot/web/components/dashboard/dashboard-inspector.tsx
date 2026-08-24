"use client";

import type { DashboardQueryReceipt } from "~/lib/dashboard/api-data-source";

import styles from "./dashboard-runtime.module.css";

export function DashboardInspector({
  receipt,
}: {
  receipt?: DashboardQueryReceipt;
}) {
  return (
    <aside className={styles.inspector} aria-label="Query inspector">
      <h2>Definition & query receipt</h2>
      {!receipt ? (
        <p>Select a loaded chart to inspect its governed query.</p>
      ) : (
        <dl>
          <dt>Execution</dt>
          <dd>{receipt.execution_id}</dd>
          <dt>Dashboard result</dt>
          <dd>{receipt.dashboard_result_id}</dd>
          <dt>Completeness</dt>
          <dd>{receipt.completeness}</dd>
          <dt>Cache</dt>
          <dd>{receipt.cache_state}</dd>
          <dt>Tables</dt>
          <dd>{receipt.tables.join(", ")}</dd>
          <dt>SQL hash</dt>
          <dd>{receipt.sql_hash}</dd>
          <dt>Parameter hash</dt>
          <dd>{receipt.parameter_hash}</dd>
        </dl>
      )}
      {receipt?.semantic_definition ? (
        <details open>
          <summary>Metric and attribute definition</summary>
          <pre>{JSON.stringify(receipt.semantic_definition, null, 2)}</pre>
        </details>
      ) : null}
      {receipt?.compiled_sql ? (
        <details>
          <summary>Compiled MSSQL</summary>
          <pre>{receipt.compiled_sql}</pre>
        </details>
      ) : null}
    </aside>
  );
}
