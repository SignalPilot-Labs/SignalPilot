// Timezone choices for the refresh schedule. The browser zone leads, then a
// short list of common IANA zones; anything else is typed in by hand.

export const COMMON_TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Toronto",
  "America/Sao_Paulo",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Amsterdam",
  "Europe/Warsaw",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
  "Pacific/Auckland",
] as const;

/** The viewer's IANA zone, "UTC" when the runtime cannot say. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** True when `Intl` accepts the zone; unknown zones throw a RangeError. */
export function isValidTimeZone(zone: string): boolean {
  if (!zone.trim()) return false;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

/**
 * Select options: browser zone first, then the common list, then the
 * current value when it is not in either (so an edited dashboard never
 * shows a blank select).
 */
export function timezoneOptions(current: string | null | undefined, browser = browserTimeZone()): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const zone of [browser, ...COMMON_TIMEZONES, current ?? ""]) {
    if (!zone || seen.has(zone)) continue;
    seen.add(zone);
    out.push(zone);
  }
  return out;
}
