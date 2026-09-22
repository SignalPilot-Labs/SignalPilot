/**
 * Number formatting for the usage pages. Usage amounts are neutral facts,
 * never an error state, so nothing here carries a colour.
 */

/** 999 -> "999", 12_345 -> "12.3k", 1_234_567 -> "1.2M", 2_500_000_000 -> "2.5B". */
export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "0";
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  const scale = (n: number, suffix: string) => {
    const scaled = abs / n;
    const text = scaled >= 100 ? scaled.toFixed(0) : scaled.toFixed(1).replace(/\.0$/, "");
    return `${sign}${text}${suffix}`;
  };
  if (abs >= 1e9) return scale(1e9, "B");
  if (abs >= 1e6) return scale(1e6, "M");
  if (abs >= 1e3) return scale(1e3, "k");
  return `${sign}${abs.toLocaleString("en-US")}`;
}

/** 1234.5 -> "$1,234.50"; null -> "$0.00". Always two decimals. */
export function formatUsd(value: number | null | undefined): string {
  const n = value !== null && value !== undefined && Number.isFinite(value) ? value : 0;
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** Full integer with thousands separators for table cells. */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "0";
  return Math.round(value).toLocaleString("en-US");
}

/** "2026-09-14" -> "Sep 14" for chart ticks. */
export function formatDayTick(date: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!m) return date;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[Number(m[2]) - 1]} ${Number(m[3])}`;
}

/** Epoch seconds or milliseconds -> seconds, for TimeAgo. Null when unknown. */
export function toEpochSeconds(ts: number | null | undefined): number | null {
  if (ts === null || ts === undefined || !Number.isFinite(ts) || ts <= 0) return null;
  return ts > 1e11 ? ts / 1000 : ts;
}
