import { describe, expect, it } from "vitest";

import { DASHBOARD_REFRESH_OPTIONS } from "~/lib/api/dashboards";

import {
  absoluteLocalTime,
  durationLabel,
  intervalOptionLabel,
  isValidAnchorTime,
  parseIntervalValue,
  refreshStatusLine,
  refreshSummary,
  relativeTime,
  timezoneShortLabel,
} from "./format";
import { isValidTimeZone, timezoneOptions } from "./timezones";

const NOW = Date.parse("2026-09-08T15:00:00Z");
const at = (ms: number) => new Date(NOW + ms).toISOString();

describe("relativeTime", () => {
  it("rounds to the coarsest sensible unit", () => {
    expect(relativeTime(at(-10_000), NOW)).toBe("just now");
    expect(relativeTime(at(-5 * 60_000), NOW)).toBe("5 min ago");
    expect(relativeTime(at(-3 * 3_600_000), NOW)).toBe("3 h ago");
    expect(relativeTime(at(-2 * 86_400_000), NOW)).toBe("2 d ago");
    expect(relativeTime(at(4 * 3_600_000), NOW)).toBe("in 4 h");
    expect(relativeTime(at(20_000), NOW)).toBe("in a moment");
  });
  it("falls back to a date beyond two weeks and to never when missing", () => {
    expect(relativeTime(at(-40 * 86_400_000), NOW)).toMatch(/Jul \d+, 2026/);
    expect(relativeTime(null, NOW)).toBe("never");
    expect(relativeTime("not a date", NOW)).toBe("never");
  });
});

describe("absoluteLocalTime", () => {
  it("formats in the requested zone and adds the year only when it differs", () => {
    expect(absoluteLocalTime(at(19 * 3_600_000), { timeZone: "America/New_York", now: NOW })).toBe(
      "Sep 9, 06:00",
    );
    expect(absoluteLocalTime("2027-01-02T10:30:00Z", { timeZone: "UTC", now: NOW })).toBe(
      "Jan 2, 2027, 10:30",
    );
    expect(absoluteLocalTime(null)).toBe("");
  });
});

describe("refreshSummary", () => {
  it("labels daily schedules with the anchor and a short zone", () => {
    expect(
      refreshSummary({ interval_minutes: 1440, anchor_time: "06:00", timezone: "America/New_York", mode: "sql" }),
    ).toBe("Daily at 06:00 ET");
    expect(
      refreshSummary({ interval_minutes: 1440, anchor_time: null, timezone: "UTC", mode: "sql" }),
    ).toBe("Daily at 06:00 UTC");
  });
  it("labels sub-daily intervals by the option label and off as Off", () => {
    expect(refreshSummary({ interval_minutes: 240, anchor_time: "06:00", timezone: "UTC", mode: "sql" })).toBe(
      "Every 4 hours",
    );
    expect(refreshSummary({ interval_minutes: 15, anchor_time: "06:00", timezone: "UTC", mode: "sql" })).toBe(
      "Every 15 minutes",
    );
    expect(refreshSummary({ interval_minutes: null, anchor_time: null, timezone: "UTC", mode: "sql" })).toBe("Off");
    expect(refreshSummary(null)).toBe("Off");
  });
});

describe("refreshStatusLine", () => {
  const refresh = { interval_minutes: 1440 as const, anchor_time: "06:00", timezone: "America/New_York", mode: "sql" as const };
  it("shows the last refresh and the next one in local time", () => {
    expect(
      refreshStatusLine(
        { refresh, last_refresh_at: at(-3 * 3_600_000), next_refresh_at: at(19 * 3_600_000) },
        { now: NOW, timeZone: "America/New_York" },
      ),
    ).toBe("Refreshed 3 h ago · next Sep 9, 06:00");
  });
  it("says refresh off when the schedule is off", () => {
    const off = { ...refresh, interval_minutes: null };
    expect(refreshStatusLine({ refresh: off, last_refresh_at: null, next_refresh_at: null }, { now: NOW })).toBe(
      "Refresh off",
    );
    expect(
      refreshStatusLine({ refresh: off, last_refresh_at: at(-60_000), next_refresh_at: null }, { now: NOW }),
    ).toBe("Refreshed 1 min ago · Refresh off");
  });
  it("says never refreshed for a scheduled dashboard with no run yet", () => {
    expect(refreshStatusLine({ refresh, last_refresh_at: null, next_refresh_at: null }, { now: NOW })).toBe(
      "Never refreshed",
    );
  });
});

describe("interval options", () => {
  it("round-trips every option through the select value", () => {
    for (const option of DASHBOARD_REFRESH_OPTIONS) {
      const raw = option.value == null ? "" : String(option.value);
      expect(parseIntervalValue(raw)).toBe(option.value);
      expect(intervalOptionLabel(parseIntervalValue(raw))).toBe(option.label);
    }
    expect(parseIntervalValue("37")).toBeNull();
  });
});

describe("timezones", () => {
  it("shortens known zones and falls back to the city", () => {
    expect(timezoneShortLabel("America/Los_Angeles")).toBe("PT");
    expect(timezoneShortLabel("Europe/Paris")).toBe("CET");
    expect(timezoneShortLabel("America/Argentina/Buenos_Aires")).toBe("Buenos Aires");
    expect(timezoneShortLabel(null)).toBe("");
  });
  it("lists the browser zone first and keeps an unusual current zone", () => {
    const options = timezoneOptions("Asia/Yerevan", "Europe/Berlin");
    expect(options[0]).toBe("Europe/Berlin");
    expect(options.filter((zone) => zone === "Europe/Berlin")).toHaveLength(1);
    expect(options).toContain("Asia/Yerevan");
  });
  it("validates zones with Intl", () => {
    expect(isValidTimeZone("America/New_York")).toBe(true);
    expect(isValidTimeZone("Mars/Olympus")).toBe(false);
    expect(isValidTimeZone("")).toBe(false);
  });
});

describe("durationLabel and anchors", () => {
  it("formats durations at second, minute and hour scale", () => {
    expect(durationLabel(at(0), at(12_000))).toBe("12 s");
    expect(durationLabel(at(0), at(184_000))).toBe("3 min 4 s");
    expect(durationLabel(at(0), at(3_720_000))).toBe("1 h 2 min");
    expect(durationLabel(at(-30_000), null, NOW)).toBe("30 s");
  });
  it("accepts only HH:MM anchors", () => {
    expect(isValidAnchorTime("06:00")).toBe(true);
    expect(isValidAnchorTime("23:59")).toBe(true);
    expect(isValidAnchorTime("24:00")).toBe(false);
    expect(isValidAnchorTime("6:00")).toBe(false);
  });
});
