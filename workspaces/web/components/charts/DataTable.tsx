import type { ChartRunResponse } from "@/lib/api/types";

interface DataTableProps {
  run: ChartRunResponse;
}

const MAX_ROWS = 200;

export function DataTable({ run }: DataTableProps) {
  const displayRows = run.rows.slice(0, MAX_ROWS);
  const truncated = run.truncated || run.rows.length > MAX_ROWS;

  return (
    <div className="max-h-80 overflow-auto rounded border border-border">
      <table className="min-w-full text-sm">
        <thead className="sticky top-0 z-10 bg-surface">
          <tr>
            {run.columns.map((col) => (
              <th
                key={col.name}
                className="px-3 py-2 text-left font-medium text-muted border-b border-border whitespace-nowrap"
              >
                {col.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {displayRows.map((row, rowIdx) => (
            <tr key={rowIdx} className="hover:bg-surface transition-colors">
              {row.map((cell, cellIdx) => (
                <td
                  key={cellIdx}
                  className="px-3 py-1.5 text-fg border-b border-border/50 whitespace-nowrap"
                >
                  {cell == null ? <span className="text-muted">—</span> : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {truncated && (
        <p className="px-3 py-2 text-xs text-muted bg-surface border-t border-border">
          Showing first {displayRows.length} rows
        </p>
      )}
    </div>
  );
}
