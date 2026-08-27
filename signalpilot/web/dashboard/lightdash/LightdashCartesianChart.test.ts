import { describe, expect, it } from "vitest";

import { buildLightdashCartesianOption } from "~/dashboard/lightdash/LightdashCartesianChart";
import type {
  LightdashCartesianInput,
  LightdashResultRow,
} from "~/lib/dashboard/contracts";

function row(dimension: unknown, metric: number): LightdashResultRow {
  return {
    dimension: { value: { raw: dimension, formatted: String(dimension) } },
    metric: { value: { raw: metric, formatted: `$${metric}` } },
  };
}

function input(
  seriesType: "bar" | "line" | "area",
  dimensionType: "string" | "timestamp",
  rows: LightdashResultRow[],
): LightdashCartesianInput {
  return {
    chartType: "cartesian",
    seriesType,
    xField: "dimension",
    yFields: ["metric"],
    rows,
    fields: {
      dimension: {
        fieldId: "dimension",
        label: "Dimension",
        type: dimensionType,
        role: "dimension",
      },
      metric: {
        fieldId: "metric",
        label: "Revenue",
        type: "number",
        role: "metric",
        format: "currency:USD",
        currencyCode: "USD",
      },
    },
    locale: "pt-BR",
    timezone: "America/Sao_Paulo",
  };
}

describe("Lightdash cartesian presentation defaults", () => {
  it("renders dense time series without markers, long labels, or a redundant legend", () => {
    const option = buildLightdashCartesianOption(
      input(
        "area",
        "timestamp",
        Array.from({ length: 40 }, (_, index) =>
          row(
            `2026-08-${String((index % 28) + 1).padStart(2, "0")}T12:00:00Z`,
            index * 1000,
          ),
        ),
      ),
    ) as Record<string, any>;
    expect(option.animation).toBe(false);
    expect(option.tooltip.appendTo).toBe("body");
    expect(option.tooltip.confine).toBe(false);
    expect(option.tooltip.extraCssText).toContain("100vw - 24px");
    expect(option.legend.show).toBe(false);
    expect(option.series[0].showSymbol).toBe(false);
    expect(option.series[0].sampling).toBe("lttb");
    expect(option.xAxis.data[0]).toMatch(/ago\./);
    expect(option.yAxis.axisLabel.formatter(70_000)).not.toContain("70.000,00");
  });

  it("uses scrollable horizontal bars for long ranked category lists", () => {
    const option = buildLightdashCartesianOption(
      input(
        "bar",
        "string",
        Array.from({ length: 20 }, (_, index) =>
          row(`Long account name ${index + 1}`, 500_000 - index),
        ),
      ),
    ) as Record<string, any>;
    expect(option.xAxis.type).toBe("value");
    expect(option.yAxis.type).toBe("category");
    expect(option.yAxis.inverse).toBe(true);
    expect(option.dataZoom).toHaveLength(2);
    expect(option.series[0].barMaxWidth).toBe(24);
  });
});
