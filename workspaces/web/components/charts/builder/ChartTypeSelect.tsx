"use client";

import { CHART_TYPES, type ChartType } from "@/lib/charts/types";
import { FIELD_INPUT_CLASS } from "@/components/ui/button-classes";

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
      className={FIELD_INPUT_CLASS}
    >
      {CHART_TYPES.map((t) => (
        <option key={t} value={t}>
          {CHART_TYPE_LABELS[t]}
        </option>
      ))}
    </select>
  );
}
