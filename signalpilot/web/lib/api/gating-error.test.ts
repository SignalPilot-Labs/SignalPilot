import { describe, expect, it } from "vitest";
import { ApiRequestError, gatingError } from "./client";

describe("gatingError", () => {
  it("reads a 402 plan_required with the keys at the top level", () => {
    const err = new ApiRequestError(
      402,
      '{"error":"plan_required","tier":"free","detail":{"error":"plan_required","tier":"free"}}',
    );
    expect(gatingError(err)).toEqual({ status: 402, error: "plan_required", tier: "free" });
  });

  it("reads a 503 not_available_in_deployment from detail alone", () => {
    const err = new ApiRequestError(
      503,
      '{"detail":{"error":"not_available_in_deployment","capability":"evals"}}',
    );
    expect(gatingError(err)).toEqual({
      status: 503,
      error: "not_available_in_deployment",
      capability: "evals",
    });
  });

  it("returns null for other statuses, other bodies and non-request errors", () => {
    expect(gatingError(new ApiRequestError(402, "Payment Required"))).toBeNull();
    expect(gatingError(new ApiRequestError(503, '{"detail":"Chat is disabled"}'))).toBeNull();
    expect(gatingError(new ApiRequestError(404, '{"error":"plan_required","tier":"free"}'))).toBeNull();
    expect(gatingError(new Error("402: nope"))).toBeNull();
    expect(gatingError(null)).toBeNull();
  });
});
