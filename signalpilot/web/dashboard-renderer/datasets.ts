/**
 * Dataset loading helpers: RFC 4180 CSV/TSV parsing with numeric coercion and
 * JSON arrays of flat objects.
 *
 * The delimited parser is a copy of `parseDelimited` from
 * `components/chat/chat-csv-preview.tsx` (not imported: this package must
 * build without the rest of the web app).
 *
 * Print-path module: relative imports only, no React, no DOM.
 */
import { NUMERIC_TEXT } from "./format";
import type { DashboardCellValue, DashboardSpec } from "./schema";

export type DatasetRows = Record<string, DashboardCellValue>[];

/** Parse RFC 4180 delimited text into records (no header handling). */
export function parseDelimitedRecords(text: string, delimiter: string): string[][] {
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
  while (index < text.length) {
    const char = text[index];
    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
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
  return records;
}

/**
 * Cells that are fully numeric become numbers; empty cells become null. The
 * numeric forms match the Python loader's `float()` for plain decimals (see
 * NUMERIC_TEXT for the forms Python accepts beyond that).
 */
export function coerceCell(cell: string): DashboardCellValue {
  const trimmed = cell.trim();
  if (trimmed === "") return null;
  if (NUMERIC_TEXT.test(trimmed)) {
    const parsed = Number(trimmed);
    if (Number.isFinite(parsed)) return parsed;
  }
  return cell;
}

function delimiterForFilename(filename: string): string {
  return /\.tsv$/i.test(filename) ? "\t" : ",";
}

function parseJsonRows(text: string, filename: string): DatasetRows {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new Error(
      `${filename}: invalid JSON (${error instanceof Error ? error.message : String(error)})`,
    );
  }
  if (!Array.isArray(parsed)) {
    throw new Error(`${filename}: JSON dataset must be an array of objects`);
  }
  return parsed.map((row, index) => {
    if (row === null || typeof row !== "object" || Array.isArray(row)) {
      throw new Error(`${filename}: row ${index} is not an object`);
    }
    const out: Record<string, DashboardCellValue> = {};
    for (const [key, value] of Object.entries(row as Record<string, unknown>)) {
      out[key] =
        value === null ||
        typeof value === "string" ||
        typeof value === "number" ||
        typeof value === "boolean"
          ? value
          : value === undefined
            ? null
            : JSON.stringify(value);
    }
    return out;
  });
}

/**
 * Parse dataset text by file extension: `.json` -> array of objects,
 * `.tsv` -> tab delimited, anything else -> comma delimited. Delimited files
 * use the first record as the header: names are trimmed and an empty name
 * stays "" (the Python loader does the same). Records whose cells are all
 * blank are skipped. Throws on unparseable input.
 */
export function parseDatasetText(text: string, filename: string): DatasetRows {
  if (/\.json$/i.test(filename)) return parseJsonRows(text, filename);
  const records = parseDelimitedRecords(
    text.charCodeAt(0) === 0xfeff ? text.slice(1) : text,
    delimiterForFilename(filename),
  );
  const header = records[0];
  if (!header || header.length === 0) return [];
  const names = header.map((name) => name.trim());
  const rows: DatasetRows = [];
  for (const record of records.slice(1)) {
    if (record.every((cell) => cell.trim() === "")) continue;
    const row: Record<string, DashboardCellValue> = {};
    names.forEach((name, index) => {
      row[name] = index < record.length ? coerceCell(record[index]) : null;
    });
    rows.push(row);
  }
  return rows;
}

/** Every dataset backed by a file, with its scratch-relative path. */
export function datasetFileRefs(
  spec: DashboardSpec,
): { name: string; path: string }[] {
  return Object.entries(spec.datasets).flatMap(([name, dataset]) =>
    typeof dataset.file === "string" ? [{ name, path: dataset.file }] : [],
  );
}

/** Datasets declared inline via `rows`. */
export function inlineDatasets(spec: DashboardSpec): Record<string, DatasetRows> {
  const out: Record<string, DatasetRows> = {};
  for (const [name, dataset] of Object.entries(spec.datasets)) {
    if (Array.isArray(dataset.rows)) out[name] = dataset.rows;
  }
  return out;
}
