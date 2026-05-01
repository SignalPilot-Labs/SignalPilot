import type { ChartRunResponse, ChartResponse } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";

interface NumberKpiProps {
  chart: ChartResponse;
  run: ChartRunResponse;
}

export function NumberKpi({ chart, run }: NumberKpiProps) {
  const firstRow = run.rows[0];
  const value = firstRow != null ? firstRow[0] : null;

  return (
    <div className="flex flex-col items-center justify-center py-8">
      <span className="text-4xl font-bold text-fg tabular-nums">
        {value != null ? formatNumber(value) : "—"}
      </span>
      <span className="mt-2 text-sm text-muted">{chart.title}</span>
    </div>
  );
}
