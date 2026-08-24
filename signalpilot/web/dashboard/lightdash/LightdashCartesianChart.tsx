"use client";

import { useMemo } from "react";
import type { EChartsOption } from "echarts";

import type { LightdashCartesianInput } from "~/lib/dashboard/contracts";
import EChartsReact from "~/dashboard/lightdash/EChartsReactWrapper";

function toEchartsValue(value: unknown): string | number | null {
  if (typeof value === "string" || typeof value === "number") return value;
  if (value instanceof Date) return value.toISOString();
  if (value === null || value === undefined) return null;
  return String(value);
}

/**
 * Focused extraction of Lightdash's SimpleChart bar rendering behavior.
 * It intentionally receives prepared Lightdash-shaped rows instead of using
 * Lightdash API/query/dashboard providers. See ../UPSTREAM.md.
 */
export function LightdashCartesianChart({
  input,
  onMarkClick,
}: {
  input: LightdashCartesianInput;
  onMarkClick: (mark: Record<string, unknown>) => void;
}) {
  const option = useMemo<EChartsOption>(() => {
    const categories = input.rows.map(
      (row) => row[input.xField]?.value.formatted ?? "—",
    );

    return {
      animation: false,
      aria: { enabled: true },
      backgroundColor: "transparent",
      color: ["#56B4E9", "#E69F00", "#009E73", "#CC79A7"],
      grid: { top: 24, right: 20, bottom: 54, left: 72 },
      legend: {
        bottom: 0,
        icon: "roundRect",
        textStyle: { color: "#A4A4AA", fontFamily: "DM Sans" },
      },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: "#202024",
        borderColor: "#3B3B42",
        textStyle: { color: "#EDEDED", fontFamily: "DM Sans" },
      },
      xAxis: {
        type: "category",
        data: categories,
        axisLine: { lineStyle: { color: "#55555C" } },
        axisTick: { show: false },
        axisLabel: { color: "#A4A4AA", interval: 0 },
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        axisLabel: { color: "#A4A4AA" },
        splitLine: { lineStyle: { color: "#333338" } },
      },
      series: input.yFields.map((field) => ({
        id: field,
        name: input.fields[field]?.label ?? field,
        type: input.seriesType === "bar" ? "bar" : "line",
        ...(input.seriesType === "bar" ? { barMaxWidth: 52 } : {}),
        ...(input.seriesType === "area" ? { areaStyle: { opacity: 0.28 } } : {}),
        itemStyle:
          input.seriesType === "bar" ? { borderRadius: [4, 4, 0, 0] } : {},
        data: input.rows.map((row, rowIndex) => ({
          value: toEchartsValue(row[field]?.value.raw),
          rowIndex,
          field,
        })),
      })),
    };
  }, [input]);

  return (
    <EChartsReact
      option={option}
      notMerge
      lazyUpdate
      style={{ width: "100%", height: "100%", minHeight: 280 }}
      onEvents={{
        click: (event: {
          dataIndex?: number;
          data?: { rowIndex?: number; field?: string };
        }) => {
          const rowIndex = event.data?.rowIndex ?? event.dataIndex;
          if (typeof rowIndex !== "number") return;
          const row = input.rows[rowIndex];
          if (!row) return;
          onMarkClick(
            Object.fromEntries(
              Object.entries(row).map(([field, value]) => [
                field,
                value.value.raw,
              ]),
            ),
          );
        },
      }}
      opts={{ renderer: "canvas" }}
    />
  );
}
