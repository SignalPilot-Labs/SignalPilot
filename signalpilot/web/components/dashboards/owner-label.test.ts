import { describe, expect, it } from "vitest";

import { isRawUserId, ownerLabel } from "./owner-label";

const owner = (created_by_label: string, created_by_user_id = "user_abc") => ({
  created_by_label,
  created_by_user_id,
});

describe("ownerLabel", () => {
  it("shows a readable label as is", () => {
    expect(ownerLabel(owner("daniel@example.com"), "user_abc")).toBe("daniel@example.com");
    expect(ownerLabel(owner("Daniel K"), null)).toBe("Daniel K");
  });

  it("turns the viewer's own raw id into You", () => {
    expect(ownerLabel(owner("user_abc"), "user_abc")).toBe("You");
    // The id column is authoritative even when the label is a different raw id.
    expect(ownerLabel(owner("user_other", "user_abc"), "user_abc")).toBe("You");
  });

  it("hides raw ids that are not the viewer's, or when the viewer is unknown", () => {
    expect(ownerLabel(owner("user_abc"), "user_zzz")).toBeNull();
    expect(ownerLabel(owner("user_abc"), null)).toBeNull();
    expect(ownerLabel(owner("user_abc"), undefined)).toBeNull();
    expect(ownerLabel(owner("  "), "user_abc")).toBeNull();
  });

  it("recognises raw ids by prefix only", () => {
    expect(isRawUserId("user_2abc")).toBe(true);
    expect(isRawUserId("username@example.com")).toBe(false);
  });
});
