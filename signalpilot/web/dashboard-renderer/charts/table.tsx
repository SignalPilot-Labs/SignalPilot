"use client";

import { useMemo } from "react";

import type { DatasetRows } from "../datasets";
import { formatValue, isNumeric } from "../format";
import type { TableChart } from "../schema";

const MAX_DOM_ROWS = 500;

export function TableTile({ chart, rows }: { chart: TableChart; rows: DatasetRows }) {
  const numeric = useMemo(
    () =>
      chart.columns.map((column) => {
        const sample = rows
          .slice(0, 50)
          .map((row) => row[column.column])
          .filter((value) => value !== null && value !== undefined && value !== "");
        return sample.length > 0 && sample.every(isNumeric);
      }),
    [chart.columns, rows],
  );
  const shown = rows.slice(0, MAX_DOM_ROWS);
  return (
    <div data-dashboard-tile="table" className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-[12px] leading-5">
          <thead className="sticky top-0 z-10 bg-[var(--sp-dash-surface)]">
            <tr>
              {chart.columns.map((column, index) => (
                <th
                  key={column.column}
                  scope="col"
                  className={`whitespace-nowrap border-b border-[var(--sp-dash-border)] px-2 py-1 font-medium text-[var(--sp-dash-text-muted)] ${
                    numeric[index] ? "text-right" : "text-left"
                  }`}
                >
                  {column.label ?? column.column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-b border-[var(--sp-dash-grid)]">
                {chart.columns.map((column, index) => {
                  const text = formatValue(row[column.column], column.format);
                  return (
                    <td
                      key={column.column}
                      className={`max-w-[320px] truncate px-2 py-1 text-[var(--sp-dash-text)] ${
                        numeric[index] ? "text-right tabular-nums" : "text-left"
                      }`}
                      title={text}
                    >
                      {text}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > shown.length ? (
        <div className="flex-none border-t border-[var(--sp-dash-border)] px-2 py-1 text-[11px] text-[var(--sp-dash-text-muted)]">
          Showing {shown.length.toLocaleString()} of {rows.length.toLocaleString()} rows
        </div>
      ) : null}
    </div>
  );
}
