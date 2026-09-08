"use client";

import type { CSSProperties } from "react";
import type {
  DashboardSampleChart,
  DashboardSampleResult,
  RunStep,
} from "~/lib/chat-run-steps";
import { InputPills, ProgressRail, SkeletonRows, plural } from "../card-primitives";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";
import { DataTable } from "./data-table";

/**
 * Dashboard data-check card: `dashboard_sample_data`. One row per checked
 * chart with its id, type, prepared row count, columns, the issue list and
 * a small table of the sample rows the tool returned.
 */

const INPUT_KEYS = ["path", "chart_ids", "limit"] as const;
const CASCADE_CAP = 24;

function sampleResult(step: RunStep): DashboardSampleResult | null {
  return step.result?.kind === "dashboard_sample" ? step.result : null;
}

export function summarizeDashboardSample(step: RunStep): ToolCardSummary {
  const result = sampleResult(step);
  const failed = step.status === "failed";
  const title = "Dashboard data check";
  if (!result) return { title, stat: null, ok: !failed };
  if (!result.dashboardValid) {
    return { title, stat: "invalid dashboard spec", ok: false };
  }
  const issueCount = result.charts.reduce((sum, chart) => sum + chart.issueCount, 0);
  const stat = `${plural(result.charts.length, "chart")} checked, ${plural(issueCount, "issue")}`;
  return { title, stat, ok: !failed };
}

export function DashboardSampleRunning({ step }: ToolCardContext) {
  return (
    <div data-testid="chat-dashboard-sample-card">
      <div className="px-3.5 pt-3">
        <InputPills step={step} keys={INPUT_KEYS} />
      </div>
      <SkeletonRows columns={3} rows={2} />
      <ProgressRail label="Checking dashboard data…" />
    </div>
  );
}

function Chip({ children }: { children: string }) {
  return (
    <span className="inline-flex items-center rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-1.5 py-px font-mono text-[10px] text-[var(--color-text-muted)]">
      {children}
    </span>
  );
}

function ChartRow({ chart, index }: { chart: DashboardSampleChart; index: number }) {
  const columns = chart.columns.map((column) => ({
    name: column.name,
    type: column.inferredType,
  }));
  const rows = chart.rows.map((row) => columns.map((column) => row[column.name] ?? null));
  return (
    <li
      data-testid="chat-dashboard-sample-chart"
      data-chart-id={chart.id}
      className="chat-tool-cascade-in px-3.5 py-2.5"
      style={{ "--i": Math.min(index, CASCADE_CAP) } as CSSProperties}
    >
      <div className="flex min-w-0 flex-wrap items-baseline gap-2">
        <span className="min-w-0 truncate font-mono text-[12px] font-medium text-[var(--color-text)]">
          {chart.id}
        </span>
        {chart.type && <Chip>{chart.type}</Chip>}
        <span className="ml-auto flex-none font-mono text-[10px] tabular-nums text-[var(--color-text-dim)]">
          {plural(chart.rowCount, "row")}
        </span>
      </div>
      {columns.length > 0 && (
        <p className="mt-1 truncate font-mono text-[10.5px] text-[var(--color-text-dim)]">
          {columns.map((column) => column.name).join(" · ")}
        </p>
      )}
      {chart.issues.length > 0 ? (
        <ul className="mt-1.5 space-y-0.5">
          {chart.issues.map((issue, issueIndex) => (
            <li
              key={`${issue.code}-${issueIndex}`}
              data-testid="chat-dashboard-sample-issue"
              className="text-[11px] leading-4 text-[var(--color-warning)]"
            >
              <span className="mr-1.5 font-mono text-[10px]">{issue.code}</span>
              {issue.message}
            </li>
          ))}
        </ul>
      ) : chart.issueCount > 0 ? (
        <p className="mt-1.5 text-[11px] text-[var(--color-warning)]">
          {plural(chart.issueCount, "issue")}
        </p>
      ) : null}
      {columns.length > 0 && rows.length > 0 && (
        <div className="mt-2 overflow-hidden rounded-md border border-[var(--color-border)]">
          <DataTable
            columns={columns}
            rows={rows}
            totalRows={chart.rowCount}
            maxHeightClass="max-h-48"
          />
        </div>
      )}
    </li>
  );
}

export function DashboardSampleExpanded({ step }: ToolCardContext) {
  const result = sampleResult(step);
  if (!result) {
    return (
      <div data-testid="chat-dashboard-sample-card" className="px-3.5 py-3">
        <InputPills step={step} keys={INPUT_KEYS} />
      </div>
    );
  }
  return (
    <div data-testid="chat-dashboard-sample-card">
      {!result.dashboardValid && (
        <div
          data-testid="chat-dashboard-sample-invalid"
          className="border-b border-[var(--color-border)] px-3.5 py-2.5 text-[11.5px] leading-5 text-[var(--color-error)]"
        >
          <p className="font-medium">The dashboard spec is not valid.</p>
          {result.errors.length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pl-4 font-mono text-[10.5px]">
              {result.errors.map((error, index) => (
                <li key={index}>{error}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {result.charts.length === 0 ? (
        <div className="px-3.5 py-3 text-[11.5px] text-[var(--color-text-dim)]">
          No charts were checked.
        </div>
      ) : (
        <ul className="divide-y divide-[var(--color-border)]">
          {result.charts.map((chart, index) => (
            <ChartRow key={`${chart.id}-${index}`} chart={chart} index={index} />
          ))}
        </ul>
      )}
    </div>
  );
}

registerToolCard({
  kind: "dashboard_sample",
  Icon: iconForKind("dashboard_sample"),
  accent: "data",
  summarize: summarizeDashboardSample,
  Running: DashboardSampleRunning,
  Expanded: DashboardSampleExpanded,
});
