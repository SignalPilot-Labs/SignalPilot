/**
 * Value and axis formatting (see CONTRACTS "Formatting"). Self-contained on
 * purpose: this package must build without the rest of the web app. Locale
 * is fixed to en-US.
 *
 * Print-path module: relative imports only, no React, no DOM.
 */
import type { DashboardFormat } from "./schema";

export const LOCALE = "en-US";
export const NULL_TEXT = "–"; // en dash

/**
 * Plain decimals the way Python's `float()` reads them: optional sign, digits
 * with an optional fraction, optional exponent. Python additionally accepts
 * digit-group underscores ("1_000") and "inf"/"nan" spellings; the TS side
 * stays strict, so those cells are strings here and numbers there.
 */
export const NUMERIC_TEXT = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i;
const ISO_DATE =
  /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$/;

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** Number for numbers and fully numeric strings, otherwise undefined. */
export function toNumber(value: unknown): number | undefined {
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  if (typeof value === "string" && NUMERIC_TEXT.test(value.trim())) {
    const parsed = Number(value.trim());
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

export function isNumeric(value: unknown): boolean {
  return toNumber(value) !== undefined;
}

/**
 * Epoch milliseconds for ISO dates (`YYYY-MM-DD`, or a full ISO datetime).
 * Date-only values are interpreted as UTC midnight. Returns undefined when the
 * value is not an ISO date.
 */
export function parseIsoDate(value: unknown): number | undefined {
  if (value instanceof Date) {
    return Number.isNaN(value.valueOf()) ? undefined : value.valueOf();
  }
  if (typeof value !== "string") return undefined;
  const match = ISO_DATE.exec(value.trim());
  if (!match) return undefined;
  const [, year, month, day, hour, minute, second, zone] = match;
  const timestamp =
    hour === undefined
      ? Date.UTC(Number(year), Number(month) - 1, Number(day))
      : zone === undefined
        ? Date.UTC(
            Number(year),
            Number(month) - 1,
            Number(day),
            Number(hour),
            Number(minute),
            Number(second ?? "0"),
          )
        : Date.parse(value.trim().replace(" ", "T"));
  if (Number.isNaN(timestamp)) return undefined;
  const check = new Date(timestamp);
  if (
    hour === undefined &&
    (check.getUTCMonth() !== Number(month) - 1 ||
      check.getUTCDate() !== Number(day))
  ) {
    return undefined; // e.g. 2024-02-31 rolled over
  }
  return timestamp;
}

export function isIsoDate(value: unknown): boolean {
  return parseIsoDate(value) !== undefined;
}

function currencyCode(format: DashboardFormat | undefined): string | undefined {
  return format?.startsWith("currency:") ? format.slice("currency:".length) : undefined;
}

/**
 * integer: 0 decimals grouped; decimal: 2 decimals; compact: 1.2K/3.4M;
 * percentage: value*100 with 1 decimal and %; currency:XXX: Intl currency,
 * 0 decimals when >= 1000 else 2. Nulls render as an en dash.
 */
export function formatValue(value: unknown, format?: DashboardFormat): string {
  if (value === null || value === undefined) return NULL_TEXT;
  const numeric = toNumber(value);
  if (numeric === undefined) {
    if (typeof value === "boolean") return value ? "true" : "false";
    return String(value);
  }
  if (format === "integer") {
    return new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 }).format(numeric);
  }
  if (format === "decimal") {
    return new Intl.NumberFormat(LOCALE, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(numeric);
  }
  if (format === "compact") {
    return new Intl.NumberFormat(LOCALE, {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(numeric);
  }
  if (format === "percentage") {
    return new Intl.NumberFormat(LOCALE, {
      style: "percent",
      maximumFractionDigits: 1,
    }).format(numeric);
  }
  const currency = currencyCode(format);
  if (currency) {
    const decimals = Math.abs(numeric) >= 1000 ? 0 : 2;
    return new Intl.NumberFormat(LOCALE, {
      style: "currency",
      currency,
      currencyDisplay: "narrowSymbol",
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(numeric);
  }
  return new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 2 }).format(numeric);
}

/** Short number for axis ticks: compact notation, currency/percent aware. */
export function formatAxisNumber(value: number, format?: DashboardFormat): string {
  if (!Number.isFinite(value)) return NULL_TEXT;
  if (format === "percentage") return formatValue(value, format);
  const currency = currencyCode(format);
  if (currency) {
    return new Intl.NumberFormat(LOCALE, {
      style: "currency",
      currency,
      currencyDisplay: "narrowSymbol",
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
  }
  return new Intl.NumberFormat(LOCALE, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

/** True when every parseable value is the first day of a month (UTC). */
export function allFirstOfMonth(values: unknown[]): boolean {
  let seen = 0;
  for (const value of values) {
    const timestamp = parseIsoDate(value);
    if (timestamp === undefined) continue;
    seen += 1;
    const date = new Date(timestamp);
    if (
      date.getUTCDate() !== 1 ||
      date.getUTCHours() !== 0 ||
      date.getUTCMinutes() !== 0
    ) {
      return false;
    }
  }
  return seen > 0;
}

/**
 * Axis date label: `YYYY-MM-DD`, or `MMM YYYY` when `monthly` (all values are
 * first-of-month). Accepts ISO strings or epoch milliseconds.
 */
export function formatAxisDate(value: unknown, monthly = false): string {
  const timestamp =
    typeof value === "number" ? value : parseIsoDate(value);
  if (timestamp === undefined || !Number.isFinite(timestamp)) {
    return value === null || value === undefined ? NULL_TEXT : String(value);
  }
  const date = new Date(timestamp);
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  if (monthly) return `${MONTHS[month]} ${year}`;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${year}-${pad(month + 1)}-${pad(date.getUTCDate())}`;
}
