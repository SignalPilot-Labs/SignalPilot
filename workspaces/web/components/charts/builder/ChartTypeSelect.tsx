"use client";

import { CHART_TYPES, type ChartType } from "@/lib/charts/types";

interface ChartTypeSelectProps {
  value: ChartType;
  onChange: (value: ChartType) => void;
  disabled?: boolean;
}

const CHART_TYPE_LABELS: Record<ChartType, string> = {
  bar: "Bar",
  line: "Line",
  table: "Table",
  kpi: "KPI",
};

export function ChartTypeSelect({ value, onChange, disabled }: ChartTypeSelectProps) {
  return (
    <select
      id="chart-type"
      value={value}
      onChange={(e) => onChange(e.target.value as ChartType)}
      disabled={disabled}
      className="w-full rounded-control border border-border bg-bg px-3 py-2 text-sm text-fg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
    >
      {CHART_TYPES.map((t) => (
        <option key={t} value={t}>
          {CHART_TYPE_LABELS[t]}
        </option>
      ))}
    </select>
  );
}
