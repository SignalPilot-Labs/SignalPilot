"use client";

import type { ComponentType } from "react";
import { useState } from "react";

import { LightdashCartesianChart } from "~/dashboard/lightdash/LightdashCartesianChart";
import type {
  ChartDefinition,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";
import { toLightdashCartesianInput } from "~/lib/dashboard/to-lightdash-results";

export type DashboardRendererKey = "kpi" | "table" | "bar" | "line" | "area";

type RendererProps = {
  chart: ChartDefinition;
  result: DashboardQueryResult;
  onMarkClick?: (mark: Record<string, unknown>, multiselect: boolean) => void;
  onExpandRow?: (row: Record<string, unknown>) => Promise<DashboardQueryResult>;
};

function formatValue(
  value: unknown,
  format?: string,
  logicalType?: string,
): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    if (format === "integer")
      return new Intl.NumberFormat(undefined, {
        maximumFractionDigits: 0,
      }).format(value);
    if (format === "compact")
      return new Intl.NumberFormat(undefined, {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value);
    if (format === "percentage")
      return new Intl.NumberFormat(undefined, {
        style: "percent",
        maximumFractionDigits: 1,
      }).format(value);
    if (format?.startsWith("currency:"))
      return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: format.slice(9),
      }).format(value);
    return new Intl.NumberFormat(undefined, {
      maximumFractionDigits: 2,
    }).format(value);
  }
  if (
    (logicalType === "date" || logicalType === "timestamp") &&
    typeof value === "string"
  ) {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.valueOf()))
      return new Intl.DateTimeFormat(
        undefined,
        logicalType === "date"
          ? { dateStyle: "medium" }
          : { dateStyle: "medium", timeStyle: "short" },
      ).format(parsed);
  }
  return String(value);
}

function KpiRenderer({ chart, result }: RendererProps) {
  if (chart.visualization.type !== "big_number") return null;
  const value = result.rows[0]?.[chart.visualization.config.field];
  return (
    <div data-dashboard-renderer="kpi">
      {formatValue(value, chart.visualization.config.format)}
    </div>
  );
}

function TableRenderer({ chart, result, onExpandRow }: RendererProps) {
  const [expanded, setExpanded] = useState<
    Record<number, DashboardQueryResult | "loading" | "error">
  >({});
  if (chart.visualization.type !== "table") return null;
  const columns = chart.visualization.config.columns;
  const canExpand = Boolean(onExpandRow);
  return (
    <table data-dashboard-renderer="table">
      <thead>
        <tr>
          {canExpand ? <th aria-label="Expand row" /> : null}
          {columns.map((column) => (
            <th key={column}>{column}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {result.rows.flatMap((row, index) => {
          const child = expanded[index];
          return [
            <tr key={`parent-${index}`}>
              {canExpand ? (
                <td>
                  <button
                    type="button"
                    aria-label={`Expand row ${index + 1}`}
                    onClick={async () => {
                      if (child)
                        return setExpanded((current) => {
                          const next = { ...current };
                          delete next[index];
                          return next;
                        });
                      setExpanded((current) => ({
                        ...current,
                        [index]: "loading",
                      }));
                      try {
                        const loaded = await onExpandRow!(row);
                        setExpanded((current) => ({
                          ...current,
                          [index]: loaded,
                        }));
                      } catch {
                        setExpanded((current) => ({
                          ...current,
                          [index]: "error",
                        }));
                      }
                    }}
                  >
                    {child ? "▾" : "▸"}
                  </button>
                </td>
              ) : null}
              {columns.map((column) => (
                <td key={column}>
                  {formatValue(
                    row[column],
                    undefined,
                    result.columns.find((item) => item.name === column)
                      ?.logicalType,
                  )}
                </td>
              ))}
            </tr>,
            ...(child
              ? [
                  <tr key={`child-${index}`}>
                    <td colSpan={columns.length + (canExpand ? 1 : 0)}>
                      {child === "loading" ? (
                        "Loading grouped rows…"
                      ) : child === "error" ? (
                        "Grouped rows failed to load."
                      ) : (
                        <table>
                          <tbody>
                            {child.rows.map((childRow, childIndex) => (
                              <tr key={childIndex}>
                                {child.columns.map((column) => (
                                  <td key={column.name}>
                                    {formatValue(
                                      childRow[column.name],
                                      undefined,
                                      column.logicalType,
                                    )}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </td>
                  </tr>,
                ]
              : []),
          ];
        })}
      </tbody>
    </table>
  );
}

function CartesianRenderer({ chart, result, onMarkClick }: RendererProps) {
  if (chart.visualization.type !== "cartesian") return null;
  return (
    <div
      data-dashboard-renderer={chart.visualization.config.seriesType}
      style={{ height: "100%" }}
    >
      <LightdashCartesianChart
        input={toLightdashCartesianInput(result, chart)}
        onMarkClick={onMarkClick ?? (() => undefined)}
      />
    </div>
  );
}

export const dashboardRendererRegistry: Record<
  DashboardRendererKey,
  ComponentType<RendererProps>
> = {
  kpi: KpiRenderer,
  table: TableRenderer,
  bar: CartesianRenderer,
  line: CartesianRenderer,
  area: CartesianRenderer,
};

export function getDashboardRendererKey(
  chart: ChartDefinition,
): DashboardRendererKey {
  if (chart.visualization.type === "big_number") return "kpi";
  if (chart.visualization.type === "table") return "table";
  return chart.visualization.config.seriesType;
}

export function DashboardRenderer(props: RendererProps) {
  const Renderer =
    dashboardRendererRegistry[getDashboardRendererKey(props.chart)];
  return <Renderer {...props} />;
}
