import type { ChartResponse, ChartRunResponse } from "@/lib/api/types";
import { mapToEChartsOption } from "@/lib/echarts/map-option";
import { EChart } from "@/components/charts/EChart";
import { DataTable } from "@/components/charts/DataTable";
import { NumberKpi } from "@/components/charts/NumberKpi";
import { ChartError } from "@/components/charts/ChartError";

interface ChartCardRunError {
  error: string;
  code?: string;
}

interface ChartCardProps {
  chart: ChartResponse;
  runResult: ChartRunResponse | ChartCardRunError;
}

function isRunError(run: ChartRunResponse | ChartCardRunError): run is ChartCardRunError {
  return "error" in run;
}

export function ChartCard({ chart, runResult }: ChartCardProps) {
  if (chart.chart_type === "number") {
    return (
      <article className="rounded-card border border-border bg-surface p-4 shadow-card">
        <ChartCardBody chart={chart} runResult={runResult} />
      </article>
    );
  }

  return (
    <article className="rounded-card border border-border bg-surface p-4 shadow-card">
      <h2 className="mb-4 text-base font-semibold text-fg">{chart.title}</h2>
      <ChartCardBody chart={chart} runResult={runResult} />
    </article>
  );
}

function ChartCardBody({
  chart,
  runResult,
}: {
  chart: ChartResponse;
  runResult: ChartRunResponse | ChartCardRunError;
}) {
  if (isRunError(runResult)) {
    return <ChartError code={runResult.code} message={runResult.error} />;
  }

  const { chart_type } = chart;

  if (chart_type === "line" || chart_type === "bar") {
    const option = mapToEChartsOption(chart, runResult);
    return <EChart option={option} ariaLabel={chart.title} />;
  }

  if (chart_type === "table") {
    return <DataTable run={runResult} caption={chart.title} />;
  }

  if (chart_type === "number") {
    return <NumberKpi chart={chart} run={runResult} />;
  }

  // Exhaustive-ness guard — unknown chart_type
  return (
    <ChartError
      code="unknown_chart_type"
      message={`Unsupported chart type: ${chart_type}`}
    />
  );
}
