import { describe, expect, it } from "vitest";

import { allFirstOfMonth, formatAxisDate, formatAxisNumber, formatValue, parseIsoDate } from "./format";

describe("formatValue", () => {
  it.each([
    [null, undefined, "–"],
    [undefined, "integer", "–"],
    [1234567.891, "integer", "1,234,568"],
    [1234.5, "decimal", "1,234.50"],
    [3, "decimal", "3.00"],
    [1234, "compact", "1.2K"],
    [3400000, "compact", "3.4M"],
    [0.1234, "percentage", "12.3%"],
    [1, "percentage", "100%"],
    [1234.56, "currency:USD", "$1,235"],
    [999.5, "currency:USD", "$999.50"],
    [-1500, "currency:EUR", "-€1,500"],
    ["42.5", undefined, "42.5"],
    [42.123456, undefined, "42.12"],
    ["hello", "integer", "hello"],
    [true, undefined, "true"],
  ] as const)("formats %s with %s as %s", (value, format, expected) => {
    expect(formatValue(value, format)).toBe(expected);
  });
});

describe("formatAxisNumber", () => {
  it("uses compact notation and honors currency and percentage", () => {
    expect(formatAxisNumber(1500)).toBe("1.5K");
    expect(formatAxisNumber(1500, "currency:USD")).toBe("$1.5K");
    expect(formatAxisNumber(0.25, "percentage")).toBe("25%");
  });
});

describe("parseIsoDate", () => {
  it("parses dates and datetimes, rejects garbage", () => {
    expect(parseIsoDate("2024-03-01")).toBe(Date.UTC(2024, 2, 1));
    expect(parseIsoDate("2024-03-01T12:30:00Z")).toBe(Date.UTC(2024, 2, 1, 12, 30));
    expect(parseIsoDate("2024-03-01T12:30:00")).toBe(Date.UTC(2024, 2, 1, 12, 30));
    expect(parseIsoDate("2024-03-01 12:30:00+02:00")).toBe(Date.UTC(2024, 2, 1, 10, 30));
    expect(parseIsoDate("2024-02-31")).toBeUndefined();
    expect(parseIsoDate("March 1")).toBeUndefined();
    expect(parseIsoDate(123)).toBeUndefined();
  });
});

describe("formatAxisDate", () => {
  it("prints YYYY-MM-DD or MMM YYYY", () => {
    expect(formatAxisDate("2024-03-05")).toBe("2024-03-05");
    expect(formatAxisDate("2024-03-01", true)).toBe("Mar 2024");
    expect(formatAxisDate(Date.UTC(2024, 11, 1), true)).toBe("Dec 2024");
    expect(formatAxisDate("nope")).toBe("nope");
    expect(formatAxisDate(null)).toBe("–");
  });

  it("detects first-of-month series", () => {
    expect(allFirstOfMonth(["2024-01-01", "2024-02-01", null])).toBe(true);
    expect(allFirstOfMonth(["2024-01-01", "2024-02-15"])).toBe(false);
    expect(allFirstOfMonth(["x"])).toBe(false);
  });
});
