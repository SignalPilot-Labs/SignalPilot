"use client";

import type { DashboardLoadResult, RunStep } from "~/lib/chat-run-steps";
import { InputPills, ProgressRail, SkeletonRows, plural } from "../card-primitives";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";

/**
 * Dashboard load card: `dashboard_load_published`. The tool writes the
 * published spec into the sandbox as `artifacts/<slug>.dashboard.json`
 * and one snapshot per dataset; the card names the version it pulled, the
 * path and the dataset rows, or the refusal when the load failed.
 */

const INPUT_KEYS = ["slug", "dashboard_id", "version"] as const;

function loadResult(step: RunStep): DashboardLoadResult | null {
  return step.result?.kind === "dashboard_load" ? step.result : null;
}

/** "Revenue overview v3"; the version is left off when unknown. */
function versionLabel(dashboard: NonNullable<DashboardLoadResult["dashboard"]>): string {
  return dashboard.versionNo === null ? dashboard.name : `${dashboard.name} v${dashboard.versionNo}`;
}

export function summarizeDashboardLoad(step: RunStep): ToolCardSummary {
  const result = loadResult(step);
  const failed = step.status === "failed";
  const title = "Dashboard load";
  if (!result) return { title, stat: null, ok: !failed };
  if (result.error || !result.dashboard) {
    return { title, stat: result.message ?? result.error ?? "load failed", ok: false };
  }
  return { title, stat: `Loaded ${versionLabel(result.dashboard)}`, ok: !failed };
}

function DashboardLoadRunning({ step }: ToolCardContext) {
  return (
    <div data-testid="chat-dashboard-load-card">
      <div className="px-3.5 pt-3">
        <InputPills step={step} keys={INPUT_KEYS} />
      </div>
      <SkeletonRows columns={2} rows={2} />
      <ProgressRail label="Loading dashboard…" />
    </div>
  );
}

function DatasetTable({ datasets }: { datasets: DashboardLoadResult["datasets"] }) {
  return (
    <table data-testid="chat-dashboard-load-datasets" className="w-full text-left text-[11px]">
      <thead>
        <tr className="text-[10px] uppercase tracking-[0.06em] text-[var(--color-text-dim)]">
          <th className="pb-1 pr-2 font-medium">Dataset</th>
          <th className="pb-1 pr-2 text-right font-medium">Rows</th>
          <th className="pb-1 font-medium">Snapshot</th>
        </tr>
      </thead>
      <tbody>
        {datasets.map((dataset) => (
          <tr
            key={dataset.name}
            data-testid="chat-dashboard-load-dataset"
            data-dataset={dataset.name}
            className="border-t border-[var(--color-border)]"
          >
            <td className="py-1 pr-2 font-mono text-[var(--color-text)]">{dataset.name}</td>
            <td className="py-1 pr-2 text-right font-mono tabular-nums text-[var(--color-text-muted)]">
              {dataset.rows === null ? "—" : dataset.rows.toLocaleString()}
            </td>
            <td className="py-1 font-mono text-[10.5px] text-[var(--color-text-dim)]">
              {dataset.snapshot ?? "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DashboardLoadExpanded({ step }: ToolCardContext) {
  const result = loadResult(step);
  if (!result) {
    return (
      <div data-testid="chat-dashboard-load-card" className="px-3.5 py-3">
        <InputPills step={step} keys={INPUT_KEYS} />
      </div>
    );
  }
  if (result.error || !result.dashboard) {
    return (
      <div data-testid="chat-dashboard-load-card" className="px-3.5 py-3">
        <div
          data-testid="chat-dashboard-load-error"
          className="text-[11.5px] leading-5 text-[var(--color-error)]"
        >
          <p className="font-medium">{result.message ?? "The dashboard could not be loaded."}</p>
          {result.error && (
            <p className="mt-0.5 font-mono text-[10.5px]">{result.error}</p>
          )}
        </div>
      </div>
    );
  }
  const { dashboard } = result;
  return (
    <div data-testid="chat-dashboard-load-card" className="space-y-2.5 px-3.5 py-3">
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
        <span
          data-testid="chat-dashboard-load-name"
          className="min-w-0 truncate text-[12px] font-medium text-[var(--color-text)]"
        >
          {versionLabel(dashboard)}
        </span>
        {dashboard.chartCount !== null && (
          <span className="font-mono text-[10px] tabular-nums text-[var(--color-text-dim)]">
            {plural(dashboard.chartCount, "chart")}
          </span>
        )}
        <span className="font-mono text-[10px] text-[var(--color-text-dim)]">{dashboard.slug}</span>
      </div>
      {result.path && (
        <p
          data-testid="chat-dashboard-load-path"
          className="truncate font-mono text-[10.5px] text-[var(--color-text-muted)]"
        >
          {result.path}
        </p>
      )}
      {result.datasets.length > 0 && <DatasetTable datasets={result.datasets} />}
      {result.datasetsTruncated && (
        <p className="font-mono text-[10px] text-[var(--color-text-dim)]">
          Dataset list not shown: the result was too large for the event.
        </p>
      )}
      {result.next && (
        <p className="text-[11px] leading-4 text-[var(--color-text-dim)]">{result.next}</p>
      )}
    </div>
  );
}

registerToolCard({
  kind: "dashboard_load",
  Icon: iconForKind("dashboard_load"),
  accent: "artifact",
  summarize: summarizeDashboardLoad,
  Running: DashboardLoadRunning,
  Expanded: DashboardLoadExpanded,
});
