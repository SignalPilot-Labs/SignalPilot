import { describe, expect, it } from "vitest";

import { dashboardDialectLabel } from "./dialect-label";

describe("dashboardDialectLabel", () => {
  it("renders safe product labels for registered connection types", () => {
    expect(dashboardDialectLabel("postgres")).toBe("PostgreSQL");
    expect(dashboardDialectLabel("mssql")).toBe("SQL Server");
    expect(dashboardDialectLabel("duckdb")).toBe("DuckDB");
  });

  it("does not expose an unknown raw connection type", () => {
    expect(dashboardDialectLabel("legacy-secret-adapter")).toBe("SQL");
  });
});
