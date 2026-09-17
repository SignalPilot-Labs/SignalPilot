import { describe, expect, it } from "vitest";
import { ALLOTMENT_BAR_COLOR, INCLUDED_USAGE_COPY, splitAllotment } from "./allotment";

describe("splitAllotment", () => {
  it("reports usage within the allotment with no extra", () => {
    expect(splitAllotment(250, 1000)).toEqual({ fillPct: 25, usedPct: 25, extra: 0, over: false });
  });

  it("caps the fill at 100 and reports the excess as extra", () => {
    const split = splitAllotment(1400, 1000);
    expect(split.fillPct).toBe(100);
    expect(split.usedPct).toBe(140);
    expect(split.extra).toBe(400);
    expect(split.over).toBe(true);
  });

  it("treats exactly the allotment as fully used but not over", () => {
    expect(splitAllotment(1000, 1000)).toMatchObject({ fillPct: 100, extra: 0, over: false });
  });

  it("is empty without an allotment", () => {
    expect(splitAllotment(50, 0)).toEqual({ fillPct: 0, usedPct: 0, extra: 0, over: false });
  });

  it("uses neutral copy and the normal bar colour, never the error token", () => {
    expect(INCLUDED_USAGE_COPY).toBe(
      "Included usage used. Additional usage is billed as extra cost.",
    );
    expect(INCLUDED_USAGE_COPY).not.toMatch(/exceed|over budget|limit reached/i);
    expect(ALLOTMENT_BAR_COLOR).not.toContain("color-error");
  });
});
