/**
 * SVG text drawing for kpi and table tiles (screenshot path only). These are
 * approximations of the HTML tiles: same content and alignment, plain text.
 *
 * Print-path module: relative imports only, no React, no DOM.
 */
import type { DatasetRows } from "../datasets";
import { formatValue, isNumeric } from "../format";
import type { KpiChart, TableChart } from "../schema";
import type { ThemeTokens } from "../theme";

/** Average glyph width as a fraction of the font size (DM Sans estimate). */
export const CHAR_WIDTH_EM = 0.55;
export const TABLE_MAX_BODY_ROWS = 12;
export const TABLE_MIN_COLUMN_WIDTH = 60;

export function escapeXml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

export function estimateTextWidth(text: string, fontSize: number): number {
  return text.length * fontSize * CHAR_WIDTH_EM;
}

/** Clip text with an ellipsis so it fits `maxWidth` (measured by estimate). */
export function truncateText(text: string, maxWidth: number, fontSize: number): string {
  if (estimateTextWidth(text, fontSize) <= maxWidth) return text;
  const charWidth = fontSize * CHAR_WIDTH_EM;
  const fit = Math.max(0, Math.floor(maxWidth / charWidth) - 1);
  return fit <= 0 ? "…" : `${text.slice(0, fit)}…`;
}

export type TextStyle = {
  size: number;
  color: string;
  weight?: 400 | 500 | 600;
  anchor?: "start" | "middle" | "end";
  family: string;
};

export function svgText(x: number, y: number, text: string, style: TextStyle): string {
  const attrs = [
    `x="${x.toFixed(1)}"`,
    `y="${y.toFixed(1)}"`,
    `font-family="${escapeXml(style.family)}"`,
    `font-size="${style.size}"`,
    `font-weight="${style.weight ?? 400}"`,
    `fill="${style.color}"`,
    `text-anchor="${style.anchor ?? "start"}"`,
  ];
  return `<text ${attrs.join(" ")}>${escapeXml(text)}</text>`;
}

/** Greedy word wrap by estimated width; returns at most `maxLines` lines. */
export function wrapText(
  text: string,
  maxWidth: number,
  fontSize: number,
  maxLines: number,
): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (estimateTextWidth(candidate, fontSize) <= maxWidth || !current) {
      current = candidate;
    } else {
      lines.push(current);
      current = word;
    }
    if (lines.length === maxLines) break;
  }
  if (lines.length < maxLines && current) lines.push(current);
  if (lines.length === maxLines && words.length) {
    lines[maxLines - 1] = truncateText(lines[maxLines - 1], maxWidth, fontSize);
  }
  return lines;
}

/**
 * KPI body: value 28px semibold, comparison 12px muted underneath. Coordinates
 * are relative to the body origin; `width`/`height` are the body size.
 */
export function kpiBodySvg(
  chart: KpiChart,
  rows: DatasetRows,
  tokens: ThemeTokens,
  width: number,
  height: number,
): string {
  const first = rows[0];
  const value = formatValue(first?.[chart.value.column], chart.value.format);
  const valueSize = 28;
  const valueText = truncateText(value, width, valueSize);
  const parts: string[] = [];
  const hasComparison = Boolean(chart.comparison) && first !== undefined;
  const valueY = hasComparison ? Math.max(valueSize, height / 2 - 2) : height / 2 + valueSize / 3;
  parts.push(
    svgText(0, valueY, valueText, {
      size: valueSize,
      weight: 600,
      color: tokens.text,
      family: tokens.fontFamily,
    }),
  );
  if (chart.comparison && first) {
    const label = chart.comparison.label ?? chart.comparison.column;
    const comparison = `${label}: ${formatValue(first[chart.comparison.column], chart.comparison.format)}`;
    parts.push(
      svgText(0, valueY + 18, truncateText(comparison, width, 12), {
        size: 12,
        color: tokens.textMuted,
        family: tokens.fontFamily,
      }),
    );
  }
  return parts.join("");
}

export function tableColumnWidths(
  columns: { column: string; label?: string }[],
  rows: DatasetRows,
  width: number,
  fontSize: number,
): number[] {
  const estimates = columns.map((column) => {
    const header = column.label ?? column.column;
    let widest = estimateTextWidth(header, fontSize);
    for (const row of rows.slice(0, TABLE_MAX_BODY_ROWS)) {
      widest = Math.max(widest, estimateTextWidth(String(row[column.column] ?? ""), fontSize));
    }
    return Math.max(TABLE_MIN_COLUMN_WIDTH, widest + 16);
  });
  const total = estimates.reduce((sum, value) => sum + value, 0);
  if (total <= 0) return columns.map(() => width / columns.length);
  const scale = width / total;
  return estimates.map((value) => Math.max(TABLE_MIN_COLUMN_WIDTH, value * scale));
}

/**
 * Table body: header row + up to 12 body rows. Numeric columns right-aligned,
 * cell text clipped with an ellipsis. Coordinates relative to the body origin.
 */
export function tableBodySvg(
  chart: TableChart,
  rows: DatasetRows,
  tokens: ThemeTokens,
  width: number,
  height: number,
): string {
  const fontSize = 12;
  const rowHeight = 22;
  const padding = 6;
  const widths = tableColumnWidths(chart.columns, rows, width, fontSize);
  const numeric = chart.columns.map((column) => {
    const sample = rows.slice(0, TABLE_MAX_BODY_ROWS).map((row) => row[column.column]);
    const nonNull = sample.filter((value) => value !== null && value !== undefined && value !== "");
    return nonNull.length > 0 && nonNull.every(isNumeric);
  });
  const maxRows = Math.max(0, Math.min(TABLE_MAX_BODY_ROWS, Math.floor(height / rowHeight) - 1));
  const body = rows.slice(0, maxRows);
  const parts: string[] = [];
  let x = 0;
  const cell = (
    columnIndex: number,
    y: number,
    text: string,
    color: string,
    weight: 400 | 500 | 600,
  ) => {
    const columnWidth = widths[columnIndex];
    const usable = columnWidth - padding * 2;
    const clipped = truncateText(text, usable, fontSize);
    const right = numeric[columnIndex];
    return svgText(right ? x + columnWidth - padding : x + padding, y, clipped, {
      size: fontSize,
      color,
      weight,
      anchor: right ? "end" : "start",
      family: tokens.fontFamily,
    });
  };
  chart.columns.forEach((column, index) => {
    parts.push(cell(index, rowHeight - 7, column.label ?? column.column, tokens.textMuted, 500));
    x += widths[index];
  });
  parts.push(
    `<line x1="0" y1="${rowHeight}" x2="${width.toFixed(1)}" y2="${rowHeight}" stroke="${tokens.border}" stroke-width="1"/>`,
  );
  body.forEach((row, rowIndex) => {
    x = 0;
    const y = rowHeight * (rowIndex + 2) - 7;
    chart.columns.forEach((column, index) => {
      parts.push(cell(index, y, formatValue(row[column.column], column.format), tokens.text, 400));
      x += widths[index];
    });
    const lineY = rowHeight * (rowIndex + 2);
    parts.push(
      `<line x1="0" y1="${lineY}" x2="${width.toFixed(1)}" y2="${lineY}" stroke="${tokens.gridLine}" stroke-width="0.5"/>`,
    );
  });
  if (rows.length > body.length) {
    const y = rowHeight * (body.length + 2) - 7;
    if (y < height) {
      parts.push(
        svgText(0, y, `… ${rows.length - body.length} more rows`, {
          size: 11,
          color: tokens.textMuted,
          family: tokens.fontFamily,
        }),
      );
    }
  }
  return parts.join("");
}
