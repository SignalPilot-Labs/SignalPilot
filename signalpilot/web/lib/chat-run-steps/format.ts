/** Display formatters shared by the run timeline and tool cards. */

/** "1204" → "1,204". */
export function formatCount(n: number): string {
  return n.toLocaleString("en-US");
}

/** "312 ms" under a second, "1.4 s" from a second upwards. */
export function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function csvCell(value: unknown): string {
  const str = value == null ? "" : String(value);
  return str.includes(",") || str.includes('"') || str.includes("\n")
    ? `"${str.replace(/"/g, '""')}"`
    : str;
}

/** RFC 4180 CSV: header row followed by one line per row (same quoting rules
 * as the query explorer's export). */
export function toCsv(columns: string[], rows: unknown[][]): string {
  const lines = [columns.map(csvCell).join(",")];
  for (const row of rows) {
    lines.push(row.map(csvCell).join(","));
  }
  return lines.join("\n");
}
