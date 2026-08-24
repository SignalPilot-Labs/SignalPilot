"use client";

import { useMemo } from "react";
import type { EChartsOption } from "echarts";

import type { LightdashCartesianInput } from "~/lib/dashboard/contracts";
import EChartsReact from "~/dashboard/lightdash/EChartsReactWrapper";
import { formatDashboardValue } from "~/lib/dashboard/semantic-formatter";

function toEchartsValue(value: unknown): string | number | null {
  if (typeof value === "string" || typeof value === "number") return value;
  if (value instanceof Date) return value.toISOString();
  if (value === null || value === undefined) return null;
  return String(value);
}

function axisMetricValue(
  value: number,
  input: LightdashCartesianInput,
): string {
  const field = input.fields[input.yFields[0]];
  const currencyCode =
    field?.currencyCode ??
    (field?.format?.startsWith("currency:")
      ? field.format.slice("currency:".length)
      : undefined);
  if (currencyCode) {
    return new Intl.NumberFormat(input.locale, {
      style: "currency",
      currency: currencyCode,
      currencyDisplay: "narrowSymbol",
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
  }
  if (field?.format === "percentage") {
    return formatDashboardValue(value, field, {
      locale: input.locale,
      timezone: input.timezone,
    });
  }
  return new Intl.NumberFormat(input.locale, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function axisDimensionValues(input: LightdashCartesianInput): string[] {
  const field = input.fields[input.xField];
  return input.rows.map((row) => {
    const value = row[input.xField]?.value;
    if (
      value &&
      (field?.type === "date" || field?.type === "timestamp") &&
      (typeof value.raw === "string" || value.raw instanceof Date)
    ) {
      const parsed =
        value.raw instanceof Date ? value.raw : new Date(value.raw);
      if (!Number.isNaN(parsed.valueOf())) {
        return new Intl.DateTimeFormat(input.locale, {
          day: "2-digit",
          month: "short",
          timeZone: input.timezone,
        }).format(parsed);
      }
    }
    return value?.formatted ?? "—";
  });
}

export function buildLightdashCartesianOption(
  input: LightdashCartesianInput,
): EChartsOption {
  const categories = axisDimensionValues(input);
  const horizontalBars =
    input.seriesType === "bar" &&
    input.fields[input.xField]?.type === "string" &&
    input.rows.length > 8;
  const multipleSeries = input.yFields.length > 1;
  const categoryAxis = {
    type: "category" as const,
    data: categories,
    axisLine: { lineStyle: { color: "#55555C" } },
    axisTick: { show: false },
    axisLabel: {
      color: "#A4A4AA",
      hideOverlap: true,
      ...(horizontalBars
        ? { width: 150, overflow: "truncate" as const, margin: 12 }
        : { margin: 12 }),
    },
  };
  const valueAxis = {
    type: "value" as const,
    axisLine: { show: false },
    axisLabel: {
      color: "#A4A4AA",
      formatter: (value: number) => axisMetricValue(value, input),
    },
    splitLine: { lineStyle: { color: "#333338" } },
  };

  return {
    animation: false,
    aria: { enabled: true },
    backgroundColor: "transparent",
    color: ["#56B4E9", "#E69F00", "#009E73", "#CC79A7"],
    grid: horizontalBars
      ? { top: 12, right: 34, bottom: 36, left: 172, containLabel: false }
      : {
          top: 20,
          right: 18,
          bottom: multipleSeries ? 52 : 38,
          left: 76,
          containLabel: false,
        },
    legend: multipleSeries
      ? {
          show: true,
          bottom: 0,
          icon: "roundRect",
          textStyle: { color: "#A4A4AA", fontFamily: "DM Sans" },
        }
      : { show: false },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: horizontalBars ? "shadow" : "line" },
      backgroundColor: "#202024",
      borderColor: "#3B3B42",
      textStyle: { color: "#EDEDED", fontFamily: "DM Sans" },
      formatter: (rawParameters) => {
        const parameters = Array.isArray(rawParameters)
          ? rawParameters
          : [rawParameters];
        const first = parameters[0] as { dataIndex?: number } | undefined;
        const row =
          typeof first?.dataIndex === "number"
            ? input.rows[first.dataIndex]
            : undefined;
        if (!row) return "";
        const heading = row[input.xField]?.value.formatted ?? "—";
        const lines = input.yFields.map((field) => {
          const label = input.fields[field]?.label ?? field;
          return `${label}: ${row[field]?.value.formatted ?? "—"}`;
        });
        return [heading, ...lines].join("<br/>");
      },
    },
    xAxis: horizontalBars ? valueAxis : categoryAxis,
    yAxis: horizontalBars ? { ...categoryAxis, inverse: true } : valueAxis,
    dataZoom:
      horizontalBars && input.rows.length > 10
        ? [
            {
              type: "inside",
              yAxisIndex: 0,
              startValue: 0,
              endValue: 9,
              zoomLock: true,
            },
            {
              type: "slider",
              yAxisIndex: 0,
              right: 7,
              width: 8,
              startValue: 0,
              endValue: 9,
              showDetail: false,
              showDataShadow: false,
              borderColor: "transparent",
            },
          ]
        : undefined,
    series: input.yFields.map((field) => ({
      id: field,
      name: input.fields[field]?.label ?? field,
      type: input.seriesType === "bar" ? "bar" : "line",
      ...(input.seriesType === "bar"
        ? {
            barMaxWidth: horizontalBars ? 24 : 42,
            itemStyle: {
              borderRadius: horizontalBars ? [0, 4, 4, 0] : [4, 4, 0, 0],
            },
          }
        : {
            showSymbol: false,
            sampling: "lttb" as const,
            lineStyle: { width: 2 },
            emphasis: { focus: "series" as const },
          }),
      ...(input.seriesType === "area" ? { areaStyle: { opacity: 0.16 } } : {}),
      data: input.rows.map((row, rowIndex) => ({
        value: toEchartsValue(row[field]?.value.raw),
        rowIndex,
        field,
      })),
    })),
  };
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
  onMarkClick: (mark: Record<string, unknown>, multiselect: boolean) => void;
}) {
  const option = useMemo(() => buildLightdashCartesianOption(input), [input]);

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
          event?: { event?: { metaKey?: boolean; ctrlKey?: boolean } };
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
            Boolean(event.event?.event?.metaKey || event.event?.event?.ctrlKey),
          );
        },
      }}
      opts={{ renderer: "canvas" }}
    />
  );
}
