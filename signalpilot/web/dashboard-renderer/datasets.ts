/**
 * Dataset helpers: RFC 4180 CSV parsing with numeric coercion, the snapshot
 * convention for SQL datasets, and the inline rows of static datasets.
 *
 * A SQL dataset's snapshot is written only by the sandbox helper
 * `sp.dashboard_dataset(name, connection=..., sql=...)`, always as CSV at
 * `artifacts/datasets/<name>.csv`; there is no other snapshot format.
 *
 * The CSV parser is a copy of `parseDelimited` from
 * `components/chat/chat-csv-preview.tsx` (not imported: this package must
 * build without the rest of the web app).
 *
 * Print-path module: relative imports only, no React, no DOM.
 */
import { NUMERIC_TEXT } from "./format";
import type { DashboardCellValue, DashboardSpec } from "./schema";
import { isSqlDataset } from "./schema";

export type DatasetRows = Record<string, DashboardCellValue>[];

/** Scratch-relative path of a SQL dataset's snapshot. */
export function datasetSnapshotPath(name: string): string {
  return `artifacts/datasets/${name}.csv`;
}

/** Parse RFC 4180 comma-separated text into records (no header handling). */
function parseCsvRecords(text: string): string[][] {
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
    if (char === ",") {
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
function coerceCell(cell: string): DashboardCellValue {
  const trimmed = cell.trim();
  if (trimmed === "") return null;
  if (NUMERIC_TEXT.test(trimmed)) {
    const parsed = Number(trimmed);
    if (Number.isFinite(parsed)) return parsed;
  }
  return cell;
}

/**
 * Parse a snapshot CSV. The first record is the header: names are trimmed
 * and an empty name stays "" (the Python loader does the same). Records
 * whose cells are all blank are skipped. A leading UTF-8 BOM is ignored.
 */
export function parseDatasetCsv(text: string): DatasetRows {
  const records = parseCsvRecords(text.charCodeAt(0) === 0xfeff ? text.slice(1) : text);
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

/** Every SQL dataset with the scratch-relative path of its snapshot. */
export function datasetFileRefs(
  spec: DashboardSpec,
): { name: string; path: string }[] {
  return Object.entries(spec.datasets).flatMap(([name, dataset]) =>
    isSqlDataset(dataset) ? [{ name, path: datasetSnapshotPath(name) }] : [],
  );
}

/** The rows of every static dataset, keyed by name. */
export function inlineDatasets(spec: DashboardSpec): Record<string, DatasetRows> {
  const out: Record<string, DatasetRows> = {};
  for (const [name, dataset] of Object.entries(spec.datasets)) {
    if (!isSqlDataset(dataset)) out[name] = dataset.rows;
  }
  return out;
}
