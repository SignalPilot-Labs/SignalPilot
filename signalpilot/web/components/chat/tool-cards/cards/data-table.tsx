"use client";

import { ChevronDown, ChevronUp, ChevronsUpDown, Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { formatCount } from "~/lib/chat-run-steps";
import { prefersReducedMotion, typeDot } from "../card-primitives";

/**
 * Hand-rolled result grid for the table card: sticky typed header with
 * sort carets, numeric cells right-aligned in tabular mono, dim italic
 * nulls, a row-number gutter, stable null-last client sort, 200-row render
 * windows and a staggered first paint. Scrolls inside its own wrapper only;
 * the page never scrolls horizontally.
 */

export type DataTableColumn = { name: string; type?: string | null };

export type DataTableProps = {
  columns: DataTableColumn[];
  rows: unknown[][];
  /** Rows the result holds server-side (drives "Load all"). */
  totalRows: number;
  maxHeightClass?: string;
  onLoadAll?: () => void;
  loadingAll?: boolean;
};

export const ROW_WINDOW = 200;
const STAGGER_CAP = 12;
const OBJECT_PREVIEW_CHARS = 80;
const INFER_SAMPLE_ROWS = 10;

type SortDir = "asc" | "desc";
type SortState = { col: number; dir: SortDir } | null;

/** Column type from `type`, else inferred from the first 10 rows. */
export function inferColumnType(
  column: DataTableColumn,
  rows: unknown[][],
  index: number,
): string {
  if (column.type) return column.type;
  let seen: string | null = null;
  for (const row of rows.slice(0, INFER_SAMPLE_ROWS)) {
    const value = row[index];
    if (value == null) continue;
    const kind =
      typeof value === "number"
        ? "number"
        : typeof value === "boolean"
          ? "boolean"
          : typeof value === "object"
            ? "json"
            : "string";
    if (seen && seen !== kind) return "string";
    seen = kind;
  }
  return seen ?? "unknown";
}

function isNumericType(type: string): boolean {
  return /int|float|double|decimal|numeric|number|real/.test(type.toLowerCase());
}

/** Numeric-aware comparison; nulls sort last in either direction. */
export function compareCells(a: unknown, b: unknown, dir: SortDir): number {
  const aNull = a == null;
  const bNull = b == null;
  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;
  let cmp: number;
  if (typeof a === "number" && typeof b === "number") {
    cmp = a - b;
  } else if (typeof a === "boolean" && typeof b === "boolean") {
    cmp = Number(a) - Number(b);
  } else {
    const an = typeof a === "number" ? a : Number(a);
    const bn = typeof b === "number" ? b : Number(b);
    cmp =
      Number.isFinite(an) && Number.isFinite(bn) && String(a).trim() !== "" && String(b).trim() !== ""
        ? an - bn
        : String(a).localeCompare(String(b), "en", { numeric: true });
  }
  return dir === "asc" ? cmp : -cmp;
}

/** Stable sort of row indices by one column. */
export function sortRows(rows: unknown[][], sort: SortState): unknown[][] {
  if (!sort) return rows;
  return rows
    .map((row, index) => ({ row, index }))
    .sort((x, y) => compareCells(x.row[sort.col], y.row[sort.col], sort.dir) || x.index - y.index)
    .map((entry) => entry.row);
}

function Cell({ value, numeric }: { value: unknown; numeric: boolean }) {
  if (value == null) {
    return <span className="italic text-[var(--color-text-dim)]">null</span>;
  }
  if (typeof value === "number") {
    return <span className="font-mono tabular-nums">{value}</span>;
  }
  if (typeof value === "boolean") {
    return <span className="font-mono text-[var(--color-warning)]">{String(value)}</span>;
  }
  if (typeof value === "object") {
    let json = "";
    try {
      json = JSON.stringify(value) ?? "";
    } catch {
      json = String(value);
    }
    const shown =
      json.length > OBJECT_PREVIEW_CHARS ? `${json.slice(0, OBJECT_PREVIEW_CHARS)}…` : json;
    return (
      <span title={json} className="block max-w-[20rem] truncate font-mono text-[#e3ae76]">
        {shown}
      </span>
    );
  }
  const text = String(value);
  return (
    <span
      title={text}
      className={`block max-w-[20rem] truncate ${numeric ? "font-mono tabular-nums" : ""}`}
    >
      {text}
    </span>
  );
}

function SortCaret({ dir }: { dir: SortDir | null }) {
  const cls = "h-3 w-3 flex-none";
  if (dir === "asc") return <ChevronUp className={`${cls} text-[var(--color-text)]`} />;
  if (dir === "desc") return <ChevronDown className={`${cls} text-[var(--color-text)]`} />;
  return <ChevronsUpDown className={`${cls} text-[var(--color-text-dim)] opacity-60`} />;
}

export function DataTable({
  columns,
  rows,
  totalRows,
  maxHeightClass,
  onLoadAll,
  loadingAll = false,
}: DataTableProps) {
  const [sort, setSort] = useState<SortState>(null);
  const [windows, setWindows] = useState(1);
  const [tallOverride, setTallOverride] = useState<boolean | null>(null);
  const tall = tallOverride ?? rows.length > 50;
  // Stagger only the first commit; later renders (sort, load-all) are instant.
  const firstPaint = useRef(!prefersReducedMotion());
  useEffect(() => {
    firstPaint.current = false;
  }, []);

  const types = useMemo(
    () => columns.map((column, index) => inferColumnType(column, rows, index)),
    [columns, rows],
  );
  const sorted = useMemo(() => sortRows(rows, sort), [rows, sort]);
  const shown = sorted.slice(0, windows * ROW_WINDOW);
  const remaining = sorted.length - shown.length;
  const canLoadAll = Boolean(onLoadAll) && totalRows > rows.length;
  const heightClass =
    maxHeightClass ?? (tall ? "max-h-[32rem]" : "max-h-72");

  const cycleSort = (col: number) =>
    setSort((current) => {
      if (!current || current.col !== col) return { col, dir: "asc" };
      if (current.dir === "asc") return { col, dir: "desc" };
      return null;
    });

  return (
    <div data-testid="chat-data-table" className="min-w-0">
      <div className={`${heightClass} min-w-0 overflow-auto`}>
        <table className="w-full min-w-0 border-collapse text-[11.5px] leading-5 text-[var(--color-text)]">
          <thead className="sticky top-0 z-[1] bg-[var(--color-bg-card)] shadow-[0_1px_0_var(--color-border)]">
            <tr>
              <th
                aria-label="Row"
                className="w-8 px-2 py-1.5 text-right font-mono text-[10px] font-normal text-[var(--color-text-dim)]"
              >
                #
              </th>
              {columns.map((column, index) => {
                const dir = sort?.col === index ? sort.dir : null;
                const numeric = isNumericType(types[index]);
                return (
                  <th
                    key={`${column.name}-${index}`}
                    scope="col"
                    aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none"}
                    className="px-2 py-1.5 text-left font-normal"
                  >
                    <button
                      type="button"
                      data-testid={`chat-data-table-sort-${column.name}`}
                      title={`${column.name} · ${types[index]}`}
                      onClick={() => cycleSort(index)}
                      className={`flex w-full items-center gap-1.5 font-mono text-[10.5px] text-[var(--color-text-muted)] hover:text-[var(--color-text)] ${
                        numeric ? "flex-row-reverse text-right" : ""
                      }`}
                    >
                      <span
                        aria-hidden
                        className={`h-1.5 w-1.5 flex-none rounded-full ${typeDot(types[index])}`}
                      />
                      <span className="min-w-0 truncate">{column.name}</span>
                      <SortCaret dir={dir} />
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, rowIndex) => {
              const animate = firstPaint.current && rowIndex < STAGGER_CAP;
              return (
                <tr
                  key={rowIndex}
                  className={`border-t border-[var(--color-border)]/60 hover:bg-[var(--color-bg-hover)] ${
                    animate ? "chat-tool-rows-in" : ""
                  }`}
                  style={animate ? ({ "--i": rowIndex } as CSSProperties) : undefined}
                >
                  <td className="px-2 py-1 text-right font-mono text-[10px] tabular-nums text-[var(--color-text-dim)]">
                    {rowIndex + 1}
                  </td>
                  {columns.map((column, colIndex) => {
                    const numeric = isNumericType(types[colIndex]);
                    return (
                      <td
                        key={`${column.name}-${colIndex}`}
                        className={`px-2 py-1 align-top ${numeric ? "text-right" : "text-left"}`}
                      >
                        <Cell value={row[colIndex]} numeric={numeric} />
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {!shown.length && (
              <tr>
                <td
                  colSpan={columns.length + 1}
                  className="px-3 py-4 text-center text-[11px] italic text-[var(--color-text-dim)]"
                >
                  No rows returned.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {(remaining > 0 || canLoadAll || rows.length > 20) && (
        <div className="flex flex-wrap items-center gap-2 border-t border-[var(--color-border)] px-3 py-1.5 text-[10px] text-[var(--color-text-dim)]">
          {remaining > 0 && (
            <button
              type="button"
              data-testid="chat-data-table-show-next"
              onClick={() => setWindows((value) => value + 1)}
              className="rounded-md border border-[var(--color-border)] px-2 py-0.5 text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
            >
              Show next {formatCount(Math.min(ROW_WINDOW, remaining))}
              <span className="ml-1 text-[var(--color-text-dim)]">
                · {formatCount(remaining)} hidden
              </span>
            </button>
          )}
          {canLoadAll && (
            <button
              type="button"
              data-testid="chat-data-table-load-all"
              disabled={loadingAll}
              onClick={onLoadAll}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] px-2 py-0.5 text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] disabled:cursor-wait disabled:opacity-60"
            >
              {loadingAll && <Loader2 className="h-3 w-3 animate-spin" />}
              {loadingAll ? "Loading…" : `Load all ${formatCount(totalRows)} rows`}
            </button>
          )}
          {rows.length > 20 && !maxHeightClass && (
            <button
              type="button"
              onClick={() => setTallOverride(!tall)}
              className="ml-auto hover:text-[var(--color-text-muted)]"
            >
              {tall ? "Shorter" : "Taller"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
