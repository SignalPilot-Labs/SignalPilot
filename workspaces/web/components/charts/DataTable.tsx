import type { ChartRunResponse } from "@/lib/api/types";

interface DataTableProps {
  run: ChartRunResponse;
  caption: string;
}

const MAX_ROWS = 200;

export function DataTable({ run, caption }: DataTableProps) {
  const displayRows = run.rows.slice(0, MAX_ROWS);
  const truncated = run.truncated || run.rows.length > MAX_ROWS;

  return (
    <div className="max-h-80 overflow-auto border border-[var(--color-border)]">
      <table className="min-w-full text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 z-10 bg-[var(--color-bg-card)]">
          <tr>
            {run.columns.map((col) => (
              <th
                key={col.name}
                className="px-3 py-2 text-left font-medium text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px] border-b border-[var(--color-border)] whitespace-nowrap"
              >
                {col.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {displayRows.map((row, rowIdx) => (
            <tr key={rowIdx} className="table-row-hover">
              {row.map((cell, cellIdx) => (
                <td
                  key={cellIdx}
                  className="px-3 py-1.5 text-[var(--color-text)] border-b border-[var(--color-border)] whitespace-nowrap tabular-nums"
                >
                  {cell == null ? <span className="text-[var(--color-text-dim)]">—</span> : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {truncated && (
        <p className="px-3 py-2 text-xs text-[var(--color-text-dim)] bg-[var(--color-bg-card)] border-t border-[var(--color-border)]">
          Showing first {displayRows.length} rows
        </p>
      )}
    </div>
  );
}
