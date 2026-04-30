/**
 * Pure helpers for formatting session activity data.
 * Typed against Clerk's SessionActivity interface.
 * One level of defaulting max — explicit "unknown" for genuinely missing data.
 */

import type { SessionActivity } from "@clerk/types";

/**
 * Format device info: "Chrome 123 on macOS" / "Safari on iPhone" / "unknown device"
 */
export function formatDevice(a: SessionActivity): string {
  const browser = a.browserName ?? null;
  const version = a.browserVersion ?? null;
  const device = a.deviceType ?? null;

  if (!browser && !device) {
    return "unknown device";
  }

  const browserStr = browser
    ? version
      ? `${browser} ${version}`
      : browser
    : null;

  const deviceStr = device ?? null;

  if (browserStr && deviceStr) {
    return `${browserStr} on ${deviceStr}`;
  }
  return browserStr ?? deviceStr ?? "unknown device";
}

/**
 * Format location: "San Francisco, US" / "IP 1.2.3.4" / "unknown location"
 */
export function formatLocation(a: SessionActivity): string {
  const city = a.city ?? null;
  const country = a.country ?? null;
  const ip = a.ipAddress ?? null;

  if (city && country) {
    return `${city}, ${country}`;
  }
  if (city) {
    return city;
  }
  if (country) {
    return country;
  }
  if (ip) {
    return `IP ${ip}`;
  }
  return "unknown location";
}

/**
 * Format last-active date: "2m ago" / "1h ago" / "3d ago" / exact date if >30d
 */
export function formatLastActive(date: Date): string {
  const now = Date.now();
  const diffMs = now - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffMin < 1) {
    return "just now";
  }
  if (diffMin < 60) {
    return `${diffMin}m ago`;
  }
  if (diffHour < 24) {
    return `${diffHour}h ago`;
  }
  if (diffDay <= 30) {
    return `${diffDay}d ago`;
  }
  // >30 days — exact date
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
