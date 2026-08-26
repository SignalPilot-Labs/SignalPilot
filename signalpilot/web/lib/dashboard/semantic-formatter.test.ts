import { describe, expect, it } from "vitest";

import {
  fieldLabel,
  formatDashboardCell,
  formatDashboardTimestamp,
  formatDashboardValue,
} from "~/lib/dashboard/semantic-formatter";

const context = { locale: "en-US", timezone: "America/New_York" };

describe("dashboard semantic formatter", () => {
  it("uses the same explicit currency contract for every result surface", () => {
    expect(
      formatDashboardValue(
        1234.5,
        { logicalType: "number", format: "currency:USD" },
        context,
      ),
    ).toBe("$1,234.50");
    expect(
      formatDashboardCell(
        1234.5,
        {
          name: "orders.revenue",
          label: "Revenue",
          logicalType: "number",
          nullable: false,
          format: "currency:USD",
          currencyCode: "USD",
        },
        context,
      ),
    ).toBe("$1,234.50");
    expect(
      formatDashboardValue(
        "264947291.82",
        { logicalType: "number", format: "currency:USD" },
        context,
      ),
    ).toBe("$264,947,291.82");
  });

  it("honors viewer locale and dashboard timezone for timestamps", () => {
    expect(formatDashboardTimestamp("2026-08-24T12:00:00Z", context)).toContain(
      "8:00 AM",
    );
  });

  it("uses the narrow currency symbol instead of the country-prefixed symbol", () => {
    const formatted = formatDashboardValue(
      "264947291.82",
      { logicalType: "number", format: "currency:USD" },
      { locale: "pt-BR", timezone: "America/Sao_Paulo" },
    );
    expect(formatted).toContain("$");
    expect(formatted).not.toContain("US$");
  });

  it("formats percentages, booleans, nulls, and friendly field labels", () => {
    expect(formatDashboardValue(0.123, { format: "percentage" }, context)).toBe(
      "12.3%",
    );
    expect(
      formatDashboardValue(true, { logicalType: "boolean" }, context),
    ).toBe("Yes");
    expect(formatDashboardValue(null, {}, context)).toBe("—");
    expect(fieldLabel("orders.gross_revenue")).toBe("Gross Revenue");
  });
});
