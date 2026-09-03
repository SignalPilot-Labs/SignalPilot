import { describe, expect, it } from "vitest";
import {
  ApiRequestError,
  isNotebookSessionAuthError,
  userFacingErrorMessage,
} from "./client";

describe("userFacingErrorMessage", () => {
  it("keeps ordinary request errors", () => {
    const error = new ApiRequestError(409, '{"detail":"Run is busy"}');
    expect(userFacingErrorMessage(error, "fallback")).toBe(error.message);
  });

  it("uses the fallback for non-errors", () => {
    expect(userFacingErrorMessage("boom", "fallback")).toBe("fallback");
  });

  it("silences the sandbox session-token rejection", () => {
    const error = new ApiRequestError(
      401,
      '{"detail":"Invalid notebook session token"}',
    );
    expect(userFacingErrorMessage(error, "fallback")).toBeNull();
    expect(isNotebookSessionAuthError("Invalid notebook session token.")).toBe(
      true,
    );
    expect(isNotebookSessionAuthError("Token expired")).toBe(false);
  });
});
