import { describe, expect, it } from "vitest";

import {
  DashboardQueryError,
  dashboardFailureFromCause,
  isUnsafeTruncatedSeriesError,
  semanticColumnMetadata,
} from "~/lib/dashboard/api-data-source";

describe("dashboard receipt semantic metadata", () => {
  it("recovers currency formatting from semantic metrics for cached results", () => {
    expect(
      semanticColumnMetadata(
        {
          semantic_definition: {
            metrics: [
              {
                field_id: "orders.net_revenue",
                label: "Net Revenue",
                format: "currency:USD",
              },
            ],
          },
        },
        "orders.net_revenue",
      ),
    ).toEqual({
      label: "Net Revenue",
      format: "currency:USD",
      currencyCode: "USD",
    });
  });
});

describe("dashboard failure taxonomy", () => {
  it("preserves typed safe metadata without exposing a raw server message", () => {
    const failure = dashboardFailureFromCause(
      new Error(
        '503: {"detail":{"code":"authentication_rejected","message":"Login failed for user admin with password secret","retryable":false,"connection_name":"warehouse","scope":"connection","correlation_id":"correlation-1","occurred_at":"2026-08-25T12:00:00Z","cache_fallback_available":false,"cache_state":"no_usable_cache"}}',
      ),
    );

    expect(failure).toMatchObject({
      code: "authentication_rejected",
      message: "The data source rejected its saved credentials.",
      retryable: false,
      connectionName: "warehouse",
      scope: "connection",
      correlationId: "correlation-1",
      cacheState: "no_usable_cache",
    });
    expect(failure.message).not.toContain("admin");
    expect(failure.message).not.toContain("secret");
  });

  it.each([
    [403, "permission_denied"],
    [409, "stale_dashboard_version"],
    [422, "semantic_definition_invalid"],
    [429, "rate_limited"],
    [502, "result_contract_mismatch"],
    [503, "data_source_unavailable"],
    [504, "query_timeout"],
    [500, "internal_error"],
  ] as const)("maps an untyped %s response to %s", (status, code) => {
    expect(
      dashboardFailureFromCause(
        new Error(`${status}: raw driver detail`),
        "warehouse",
      ).code,
    ).toBe(code);
  });

  it("recognizes an unsafe result-contract failure by typed code", () => {
    const cause = new DashboardQueryError(
      dashboardFailureFromCause(new Error("502: invalid result")),
    );
    expect(isUnsafeTruncatedSeriesError(cause)).toBe(true);
  });
});
