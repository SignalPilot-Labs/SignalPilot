"use client";

import { useTransition } from "react";
import type { DashboardChart } from "@/lib/dashboards/types";
import { mapDashboardChartOption } from "@/lib/echarts/map-dashboard-option";
import { refreshChart } from "@/lib/dashboards/refresh-chart";
import { useRouter } from "next/navigation";
import { EChart } from "./echart";

function formatNumber(value: unknown): string {
  if (typeof value === "number" && isFinite(value)) {
    return new Intl.NumberFormat().format(value);
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (!isNaN(parsed) && isFinite(parsed)) {
      return new Intl.NumberFormat().format(parsed);
    }
  }
  return String(value);
}

export function DashboardChartCard({
  chart,
  dashboardId,
}: {
  chart: DashboardChart;
  dashboardId: string;
}) {
  const cached = chart.cachedData;
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  function handleRefresh() {
    startTransition(async () => {
      await refreshChart(dashboardId, chart.id);
      router.refresh();
    });
  }

  return (
    <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] p-4 flex flex-col h-full hover:bg-[var(--color-bg-hover)] transition-all card-glow">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="text-[12px] font-medium tracking-[0.15em] uppercase text-[var(--color-text)] truncate">
          {chart.title}
        </h3>
        <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider ml-2 flex-shrink-0">
          {chart.chartType}
        </span>
      </div>

      {!cached ? (
        <div className="flex-1 flex items-center justify-center text-[12px] text-[var(--color-text-dim)]">
          no data — run agent to populate
        </div>
      ) : cached.rows.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-[12px] text-[var(--color-text-dim)]">
          query returned 0 rows
        </div>
      ) : (
        <div className="flex-1 min-h-0">
          <ChartRenderer chart={chart} />
        </div>
      )}

      {cached?.computedAt && (
        <div className="mt-2 flex items-center justify-between">
          <span className="text-[10px] text-[var(--color-text-dim)] tracking-wider">
            data from {new Date(cached.computedAt).toLocaleString()}
          </span>
          <button
            onClick={handleRefresh}
            disabled={isPending}
            title="Refresh chart data"
            className="text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors disabled:opacity-40"
          >
            <svg
              width="11"
              height="11"
              viewBox="0 0 12 12"
              fill="none"
              className={isPending ? "animate-spin" : ""}
            >
              <path
                d="M10 6A4 4 0 1 1 6 2"
                stroke="currentColor"
                strokeWidth="1.2"
                strokeLinecap="round"
              />
              <path d="M6 0L8 2L6 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      )}
    </div>
  );
}

function ChartRenderer({ chart }: { chart: DashboardChart }) {
  const cached = chart.cachedData!;

  if (chart.chartType === "kpi") {
    const value = cached.rows[0]?.[0];
    return (
      <dl className="flex flex-col items-center justify-center py-8">
        <dd className="font-mono tabular-nums text-3xl text-[var(--color-text)]">
          {value != null ? formatNumber(value) : "—"}
        </dd>
        <dt className="mt-2 text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px]">
          {chart.title}
        </dt>
      </dl>
    );
  }

  if (chart.chartType === "table") {
    const displayRows = cached.rows.slice(0, 200);
    return (
      <div className="max-h-80 overflow-auto border border-[var(--color-border)]">
        <table className="min-w-full text-sm">
          <thead className="sticky top-0 z-10 bg-[var(--color-bg-card)]">
            <tr>
              {cached.columns.map((col) => (
                <th
                  key={col.name}
                  className="px-3 py-2 text-left font-medium text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px] border-b border-[var(--color-border)] whitespace-nowrap"
                >
                  {col.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row, rowIdx) => (
              <tr key={rowIdx} className="hover:bg-[var(--color-bg-hover)] transition-colors">
                {row.map((cell, cellIdx) => (
                  <td
                    key={cellIdx}
                    className="px-3 py-1.5 text-[var(--color-text)] border-b border-[var(--color-border)] whitespace-nowrap tabular-nums"
                  >
                    {cell == null ? <span className="text-[var(--color-text-dim)]">—</span> : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const option = mapDashboardChartOption(chart, cached);
  return <EChart option={option} ariaLabel={chart.title} />;
}
