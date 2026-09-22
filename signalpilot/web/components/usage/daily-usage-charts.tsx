"use client";

/**
 * Two small single-series bar charts, cost and chat runs per day. Two
 * measures of different scale get two charts, never a second y axis.
 * One series per chart, so the title names it and there is no legend.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DailyUsage } from "~/lib/types";
import { formatCompact, formatDayTick, formatUsd } from "~/lib/usage-format";

const TICK = { fontSize: 10, fill: "var(--color-text-dim)", fontFamily: "monospace" };

function DailyTooltip({
  active,
  payload,
  label,
  format,
  unit,
}: {
  active?: boolean;
  payload?: Array<{ value: number }>;
  label?: string;
  format: (v: number) => string;
  unit: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-[10px] px-3 py-2">
      <p className="text-[11px] text-[var(--color-text-dim)] mb-0.5 font-mono">{label}</p>
      <p className="text-[13px] tabular-nums text-[var(--color-text)] font-mono">
        {format(payload[0].value)} {unit}
      </p>
    </div>
  );
}

function DailyBarChart({
  daily,
  dataKey,
  title,
  format,
  unit,
}: {
  daily: DailyUsage[];
  dataKey: "cost_usd" | "chat_runs";
  title: string;
  format: (v: number) => string;
  unit: string;
}) {
  return (
    <div
      className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-4 min-w-0"
      role="img"
      aria-label={`${title} per day`}
    >
      <p className="text-[11px] text-[var(--color-text-muted)] uppercase tracking-[0.08em] mb-2">
        {title}
      </p>
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={daily} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap={2}>
          <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tick={TICK}
            tickFormatter={formatDayTick}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
            minTickGap={24}
          />
          <YAxis
            tick={TICK}
            tickFormatter={(v: number) => format(v)}
            tickLine={false}
            axisLine={false}
            width={52}
            allowDecimals={false}
          />
          <Tooltip
            content={<DailyTooltip format={format} unit={unit} />}
            cursor={{ fill: "var(--color-bg-hover)" }}
          />
          <Bar dataKey={dataKey} fill="var(--color-success)" radius={[4, 4, 0, 0]} maxBarSize={20} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DailyUsageCharts({ daily }: { daily: DailyUsage[] }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <DailyBarChart daily={daily} dataKey="cost_usd" title="cost" format={formatUsd} unit="" />
      <DailyBarChart daily={daily} dataKey="chat_runs" title="chat runs" format={formatCompact} unit="runs" />
    </div>
  );
}
