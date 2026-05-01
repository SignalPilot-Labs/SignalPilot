import type { ChartRunResponse, ChartResponse } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";

interface NumberKpiProps {
  chart: ChartResponse;
  run: ChartRunResponse;
}

export function NumberKpi({ chart, run }: NumberKpiProps) {
  const firstRow = run.rows[0];
  const value = firstRow != null ? firstRow[0] : null;

  // <dd> (value) precedes <dt> (label) in source order to match visual order.
  // Screen readers still associate them as a dl group per HTML5 semantics.
  return (
    <dl className="flex flex-col items-center justify-center py-8">
      <dd className="text-4xl font-bold text-fg tabular-nums">{value != null ? formatNumber(value) : "—"}</dd>
      <dt className="mt-2 text-sm text-muted">{chart.title}</dt>
    </dl>
  );
}
