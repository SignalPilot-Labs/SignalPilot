// Formatting helpers for the published-dashboard pages: relative times,
// local absolute times, refresh schedule summaries and durations. Pure
// functions with injectable clocks so the unit tests stay deterministic.

import {
  DASHBOARD_REFRESH_OPTIONS,
  type DashboardRefreshInterval,
  type DashboardRefreshSettings,
} from "~/lib/api/dashboards";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Parse an ISO timestamp; null for missing or unparseable input. */
export function parseIso(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Coarse relative time: "just now", "5 min ago", "3 h ago", "2 d ago",
 * "in 4 h". Weeks and beyond fall back to a short absolute date so a card
 * never reads "412 d ago".
 */
export function relativeTime(
  value: string | null | undefined,
  now: number = Date.now(),
): string {
  const date = parseIso(value);
  if (!date) return "never";
  const delta = date.getTime() - now;
  const abs = Math.abs(delta);
  const future = delta > 0;
  const wrap = (text: string) => (future ? `in ${text}` : `${text} ago`);
  if (abs < 45_000) return future ? "in a moment" : "just now";
  if (abs < HOUR) return wrap(`${Math.max(1, Math.round(abs / MINUTE))} min`);
  if (abs < DAY) return wrap(`${Math.round(abs / HOUR)} h`);
  if (abs < 14 * DAY) return wrap(`${Math.round(abs / DAY)} d`);
  return shortDate(date);
}

function shortDate(date: Date, locale?: string): string {
  return new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", year: "numeric" }).format(date);
}

/**
 * Absolute wall-clock time in the viewer's zone (or an explicit one), e.g.
 * "Sep 9, 06:00". The year is added when it is not the current one.
 */
export function absoluteLocalTime(
  value: string | null | undefined,
  options: { timeZone?: string; locale?: string; now?: number } = {},
): string {
  const date = parseIso(value);
  if (!date) return "";
  const now = new Date(options.now ?? Date.now());
  const sameYear = date.getUTCFullYear() === now.getUTCFullYear();
  return new Intl.DateTimeFormat(options.locale ?? "en-US", {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: options.timeZone,
  }).format(date);
}

/** Short zone label for schedule summaries: "ET", "PT", "UTC", "CET". */
const ZONE_SHORT_LABELS: Record<string, string> = {
  UTC: "UTC",
  "Etc/UTC": "UTC",
  "America/New_York": "ET",
  "America/Chicago": "CT",
  "America/Denver": "MT",
  "America/Phoenix": "MST",
  "America/Los_Angeles": "PT",
  "America/Anchorage": "AKT",
  "Pacific/Honolulu": "HST",
  "America/Toronto": "ET",
  "America/Vancouver": "PT",
  "America/Sao_Paulo": "BRT",
  "Europe/London": "UK",
  "Europe/Dublin": "IE",
  "Europe/Paris": "CET",
  "Europe/Berlin": "CET",
  "Europe/Madrid": "CET",
  "Europe/Amsterdam": "CET",
  "Europe/Stockholm": "CET",
  "Europe/Warsaw": "CET",
  "Europe/Helsinki": "EET",
  "Europe/Athens": "EET",
  "Asia/Dubai": "GST",
  "Asia/Kolkata": "IST",
  "Asia/Singapore": "SGT",
  "Asia/Hong_Kong": "HKT",
  "Asia/Shanghai": "CST",
  "Asia/Tokyo": "JST",
  "Asia/Seoul": "KST",
  "Australia/Sydney": "AET",
  "Australia/Melbourne": "AET",
  "Australia/Perth": "AWT",
  "Pacific/Auckland": "NZT",
};

export function timezoneShortLabel(timezone: string | null | undefined): string {
  if (!timezone) return "";
  const known = ZONE_SHORT_LABELS[timezone];
  if (known) return known;
  const tail = timezone.split("/").pop() ?? timezone;
  return tail.replace(/_/g, " ");
}

/** Option label for an interval value, e.g. 240 -> "Every 4 hours". */
export function intervalOptionLabel(interval: DashboardRefreshInterval | null): string {
  return DASHBOARD_REFRESH_OPTIONS.find((option) => option.value === interval)?.label ?? "Off";
}

/** Reverse of `intervalOptionLabel` for select values ("" means off). */
export function parseIntervalValue(raw: string): DashboardRefreshInterval | null {
  if (raw === "" || raw === "off" || raw === "null") return null;
  const value = Number(raw);
  const match = DASHBOARD_REFRESH_OPTIONS.find((option) => option.value === value);
  return match?.value ?? null;
}

/**
 * Compact schedule summary for cards and headers: "Daily at 06:00 ET",
 * "Every 4 hours", "Every 15 minutes", or "Off". Sub-daily intervals omit
 * the anchor: the alignment is a detail for the settings drawer.
 */
export function refreshSummary(refresh: DashboardRefreshSettings | null | undefined): string {
  if (!refresh || refresh.interval_minutes == null) return "Off";
  const interval = refresh.interval_minutes;
  if (interval >= 1440) {
    const zone = timezoneShortLabel(refresh.timezone);
    return `Daily at ${refresh.anchor_time ?? "06:00"}${zone ? ` ${zone}` : ""}`;
  }
  return intervalOptionLabel(interval);
}

/**
 * The line under a dashboard title: "Refreshed 3 h ago · next Sep 9, 06:00"
 * or "Refresh off" (with the last refresh when there was one).
 */
export function refreshStatusLine(
  dashboard: {
    refresh: DashboardRefreshSettings;
    last_refresh_at: string | null;
    next_refresh_at: string | null;
  },
  options: { now?: number; timeZone?: string; locale?: string } = {},
): string {
  const now = options.now ?? Date.now();
  const last = dashboard.last_refresh_at
    ? `Refreshed ${relativeTime(dashboard.last_refresh_at, now)}`
    : "Never refreshed";
  if (dashboard.refresh.interval_minutes == null) {
    return dashboard.last_refresh_at ? `${last} · Refresh off` : "Refresh off";
  }
  const next = dashboard.next_refresh_at
    ? ` · next ${absoluteLocalTime(dashboard.next_refresh_at, { ...options, now })}`
    : "";
  return `${last}${next}`;
}

/** Duration between two timestamps: "12 s", "3 min 4 s", "1 h 2 min". */
export function durationLabel(
  start: string | null | undefined,
  end: string | null | undefined,
  now: number = Date.now(),
): string {
  const from = parseIso(start);
  if (!from) return "";
  const to = parseIso(end)?.getTime() ?? now;
  const ms = Math.max(0, to - from.getTime());
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min${seconds % 60 ? ` ${seconds % 60} s` : ""}`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h${minutes % 60 ? ` ${minutes % 60} min` : ""}`;
}

/** Validate an "HH:MM" 24h anchor. */
export function isValidAnchorTime(value: string): boolean {
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
}

/** Validate a slug the gateway would accept. */
export function isValidSlug(value: string): boolean {
  return /^[a-z0-9][a-z0-9-]{0,63}$/.test(value);
}
