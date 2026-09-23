import { describe, expect, it } from "vitest";
import { formatCompact, formatCount, formatDayTick, formatUsd, toEpochSeconds } from "./usage-format";

describe("formatCompact", () => {
  it("keeps small numbers whole", () => {
    expect(formatCompact(0)).toBe("0");
    expect(formatCompact(999)).toBe("999");
  });
  it("abbreviates thousands and millions with one decimal", () => {
    expect(formatCompact(12_300)).toBe("12.3k");
    expect(formatCompact(1_000)).toBe("1k");
    expect(formatCompact(1_234_567)).toBe("1.2M");
    expect(formatCompact(2_500_000_000)).toBe("2.5B");
  });
  it("drops the decimal at three digits", () => {
    expect(formatCompact(123_456)).toBe("123k");
  });
  it("treats missing values as zero", () => {
    expect(formatCompact(null)).toBe("0");
    expect(formatCompact(undefined)).toBe("0");
    expect(formatCompact(Number.NaN)).toBe("0");
  });
});

describe("formatUsd", () => {
  it("always shows two decimals with a dollar sign", () => {
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(1.5)).toBe("$1.50");
    expect(formatUsd(1234.567)).toBe("$1,234.57");
    expect(formatUsd(null)).toBe("$0.00");
  });
});

describe("formatCount and formatDayTick", () => {
  it("formats counts with separators", () => {
    expect(formatCount(1234567)).toBe("1,234,567");
    expect(formatCount(undefined)).toBe("0");
  });
  it("shortens ISO dates to month and day", () => {
    expect(formatDayTick("2026-09-14")).toBe("Sep 14");
    expect(formatDayTick("2026-01-01")).toBe("Jan 1");
    expect(formatDayTick("bad")).toBe("bad");
  });
});

describe("toEpochSeconds", () => {
  it("normalises seconds and milliseconds", () => {
    expect(toEpochSeconds(1_700_000_000)).toBe(1_700_000_000);
    expect(toEpochSeconds(1_700_000_000_000)).toBe(1_700_000_000);
    expect(toEpochSeconds(null)).toBeNull();
    expect(toEpochSeconds(0)).toBeNull();
  });
});
