"use client";

import { Download } from "lucide-react";
import { useMemo } from "react";

/**
 * Table preview for CSV and TSV conversation files.
 *
 * A small RFC 4180 parser (quotes, doubled quotes, newlines inside quotes,
 * CRLF) reads the first 2 MB. The table keeps a sticky header, caps at 500
 * rows by 50 columns, right-aligns numeric columns and reports how many
 * rows it shows.
 */

export const CSV_PREVIEW_MAX_CHARS = 2_000_000;
export const CSV_PREVIEW_MAX_ROWS = 500;
export const CSV_PREVIEW_MAX_COLS = 50;

export type ParsedDelimited = {
  header: string[];
  rows: string[][];
  /** Data rows in the parsed text (header excluded). */
  totalRows: number;
  /** Columns in the parsed text. */
  totalCols: number;
  /** True when the text was cut at the character cap before parsing. */
  truncatedText: boolean;
};

/** Split delimited text into records. Pure, no dependency. */
export function parseDelimited(
  text: string,
  delimiter = ",",
  options: { maxRows?: number; maxCols?: number; maxChars?: number } = {},
): ParsedDelimited {
  const maxRows = options.maxRows ?? CSV_PREVIEW_MAX_ROWS;
  const maxCols = options.maxCols ?? CSV_PREVIEW_MAX_COLS;
  const maxChars = options.maxChars ?? CSV_PREVIEW_MAX_CHARS;
  const truncatedText = text.length > maxChars;
  const source = truncatedText ? text.slice(0, maxChars) : text;
  const records: string[][] = [];
  let record: string[] = [];
  let field = "";
  let quoted = false;
  let index = 0;
  const pushRecord = () => {
    record.push(field);
    field = "";
    // A blank line between records is not a row.
    if (record.length > 1 || record[0] !== "") records.push(record);
    record = [];
  };
  while (index < source.length) {
    const char = source[index];
    if (quoted) {
      if (char === '"') {
        if (source[index + 1] === '"') {
          field += '"';
          index += 2;
          continue;
        }
        quoted = false;
        index += 1;
        continue;
      }
      field += char;
      index += 1;
      continue;
    }
    if (char === '"' && field === "") {
      quoted = true;
      index += 1;
      continue;
    }
    if (char === delimiter) {
      record.push(field);
      field = "";
      index += 1;
      continue;
    }
    if (char === "\r") {
      index += 1;
      continue;
    }
    if (char === "\n") {
      pushRecord();
      index += 1;
      continue;
    }
    field += char;
    index += 1;
  }
  if (field !== "" || record.length > 0) pushRecord();
  // A text cut mid-record leaves a partial last row; drop it.
  if (truncatedText && records.length > 1) records.pop();
  const header = records[0] ?? [];
  const body = records.slice(1);
  const totalCols = Math.max(header.length, ...body.map((row) => row.length), 0);
  return {
    header: header.slice(0, maxCols),
    rows: body.slice(0, maxRows).map((row) => {
      const cells = row.slice(0, maxCols);
      while (cells.length < Math.min(totalCols, maxCols)) cells.push("");
      return cells;
    }),
    totalRows: body.length,
    totalCols,
    truncatedText,
  };
}

const NUMERIC_RE = /^\s*[-+]?(?:\$|€|£)?(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?%?\s*$/;

/** True when every non-empty value in the column reads as a number. */
export function isNumericColumn(rows: string[][], column: number): boolean {
  let seen = false;
  for (const row of rows) {
    const value = row[column] ?? "";
    if (value.trim() === "") continue;
    if (!NUMERIC_RE.test(value) || !/\d/.test(value)) return false;
    seen = true;
  }
  return seen;
}

/** Delimiter by filename: tab for .tsv, comma otherwise. */
export function delimiterForFilename(filename: string): string {
  return /\.tsv$/i.test(filename) ? "\t" : ",";
}

export function ChatCsvPreview({
  text,
  filename,
  onDownload,
}: {
  text: string;
  filename: string;
  onDownload?: () => void;
}) {
  const parsed = useMemo(
    () => parseDelimited(text, delimiterForFilename(filename)),
    [text, filename],
  );
  const numeric = useMemo(
    () => parsed.header.map((_, column) => isNumericColumn(parsed.rows, column)),
    [parsed],
  );
  const shown = parsed.rows.length;
  const total = parsed.totalRows;
  const droppedCols = parsed.totalCols - parsed.header.length;
  return (
    <div data-testid="chat-csv-preview" className="flex max-h-[70vh] flex-col">
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-[12px] leading-5">
          <thead className="sticky top-0 z-10 bg-[var(--color-bg-elevated)]">
            <tr>
              {parsed.header.map((name, column) => (
                <th
                  key={column}
                  scope="col"
                  className={`whitespace-nowrap border-b border-[var(--color-border)] px-3 py-1.5 font-medium text-[var(--color-text-muted)] ${
                    numeric[column] ? "text-right" : "text-left"
                  }`}
                >
                  {name || `column_${column + 1}`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {parsed.rows.map((row, rowIndex) => (
              <tr
                key={rowIndex}
                className="border-b border-[var(--color-border)]/60 hover:bg-[var(--color-bg-hover)]"
              >
                {row.map((cell, column) => (
                  <td
                    key={column}
                    className={`max-w-[320px] truncate px-3 py-1 text-[var(--color-text)] ${
                      numeric[column] ? "text-right tabular-nums" : "text-left"
                    }`}
                    title={cell}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div
        data-testid="chat-csv-preview-footer"
        className="flex flex-none items-center justify-between gap-3 border-t border-[var(--color-border)] px-3 py-1.5 text-[11px] text-[var(--color-text-dim)]"
      >
        <span>
          Showing {shown.toLocaleString()} of {total.toLocaleString()}
          {parsed.truncatedText ? "+" : ""} rows
          {droppedCols > 0 &&
            ` · ${parsed.header.length} of ${parsed.totalCols} columns`}
        </span>
        {onDownload && (
          <button
            type="button"
            data-testid="chat-csv-preview-download"
            onClick={onDownload}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
          >
            <Download className="h-3 w-3" />
            Download
          </button>
        )}
      </div>
    </div>
  );
}
