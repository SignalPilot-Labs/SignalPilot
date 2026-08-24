"use client";

import type { ComponentType } from "react";
import { useState } from "react";

import { LightdashCartesianChart } from "~/dashboard/lightdash/LightdashCartesianChart";
import type {
  ChartDefinition,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";
import { toLightdashCartesianInput } from "~/lib/dashboard/to-lightdash-results";
import {
  fieldLabel,
  formatDashboardCell,
} from "~/lib/dashboard/semantic-formatter";

export type DashboardRendererKey = "kpi" | "table" | "bar" | "line" | "area";

type RendererProps = {
  chart: ChartDefinition;
  result: DashboardQueryResult;
  onMarkClick?: (mark: Record<string, unknown>, multiselect: boolean) => void;
  onExpandRow?: (row: Record<string, unknown>) => Promise<DashboardQueryResult>;
};

function KpiRenderer({ chart, result }: RendererProps) {
  if (chart.visualization.type !== "big_number") return null;
  const config = chart.visualization.config;
  const value = result.rows[0]?.[config.field];
  const column = result.columns.find((item) => item.name === config.field) ?? {
    name: config.field,
    logicalType: "number" as const,
    nullable: true,
  };
  return (
    <div data-dashboard-renderer="kpi">
      <strong>
        {formatDashboardCell(
          value,
          {
            ...column,
            format: config.format ?? column.format,
          },
          result,
        )}
      </strong>
      <span>{chart.title}</span>
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
            <th key={column} scope="col">
              {result.columns.find((item) => item.name === column)?.label ??
                fieldLabel(column)}
            </th>
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
                  {formatDashboardCell(
                    row[column],
                    result.columns.find((item) => item.name === column) ?? {
                      name: column,
                      logicalType: "unknown",
                      nullable: true,
                    },
                    result,
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
                                    {formatDashboardCell(
                                      childRow[column.name],
                                      column,
                                      child,
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
