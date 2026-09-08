import { describe, expect, it } from "vitest";

import {
  ARTIFACTS_MIN_WIDTH,
  ARTIFACTS_WIDTH_KEY,
  TRANSCRIPT_RESERVE,
  clampWidth,
  defaultArtifactsWidth,
  applyResizeIntent,
  resizeIntent,
  parseStoredWidth,
  readStoredWidth,
  widthBounds,
  writeStoredWidth,
} from "~/components/chat/artifacts-panel-width";

describe("artifacts panel width bounds", () => {
  it("leaves the transcript reserve to the left of the panel", () => {
    const bounds = widthBounds(1600);
    expect(bounds.min).toBe(ARTIFACTS_MIN_WIDTH);
    expect(bounds.max).toBe(1600 - TRANSCRIPT_RESERVE);
  });

  it("never reports a maximum below the minimum on a narrow window", () => {
    const bounds = widthBounds(700);
    expect(bounds.max).toBe(ARTIFACTS_MIN_WIDTH);
  });

  it("is unbounded before the container has been measured", () => {
    expect(widthBounds(0).max).toBe(Number.POSITIVE_INFINITY);
  });

  it("clamps into the bounds and rounds", () => {
    const bounds = widthBounds(1600);
    expect(clampWidth(120, bounds)).toBe(ARTIFACTS_MIN_WIDTH);
    expect(clampWidth(5000, bounds)).toBe(bounds.max);
    expect(clampWidth(700.4, bounds)).toBe(700);
    expect(clampWidth(Number.NaN, bounds)).toBe(bounds.min);
  });
});

describe("default width", () => {
  it("is the container share, inside the bounds", () => {
    expect(defaultArtifactsWidth(1600)).toBe(736);
  });

  it("falls back to the minimum before measurement", () => {
    expect(defaultArtifactsWidth(0)).toBe(ARTIFACTS_MIN_WIDTH);
  });

  it("never eats the transcript reserve on a small window", () => {
    const width = defaultArtifactsWidth(900);
    expect(width).toBeLessThanOrEqual(900 - TRANSCRIPT_RESERVE);
  });
});

describe("stored preference", () => {
  it("rejects junk and widths under the minimum", () => {
    expect(parseStoredWidth(null)).toBeNull();
    expect(parseStoredWidth("wide")).toBeNull();
    expect(parseStoredWidth("100")).toBeNull();
    expect(parseStoredWidth("640.6")).toBe(641);
  });

  it("round-trips through storage and clears on reset", () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
    };
    writeStoredWidth(storage, 700);
    expect(store.get(ARTIFACTS_WIDTH_KEY)).toBe("700");
    expect(readStoredWidth(storage)).toBe(700);
    writeStoredWidth(storage, null);
    expect(readStoredWidth(storage)).toBeNull();
  });

  it("survives storage that throws", () => {
    const storage = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    };
    expect(readStoredWidth(storage)).toBeNull();
    expect(() => writeStoredWidth(storage, 700)).not.toThrow();
  });
});

describe("keyboard resize", () => {
  const bounds = widthBounds(1600);
  const apply = (key: string, shift: boolean, width: number) => {
    const intent = resizeIntent(key, shift);
    return intent === null ? null : applyResizeIntent(intent, width, bounds);
  };

  it("widens on ArrowLeft and narrows on ArrowRight", () => {
    expect(apply("ArrowLeft", false, 700)).toBe(732);
    expect(apply("ArrowRight", false, 700)).toBe(668);
  });

  it("takes a larger step with Shift", () => {
    expect(apply("ArrowLeft", true, 700)).toBe(828);
  });

  it("snaps to the bounds with Home and End", () => {
    expect(apply("Home", false, 700)).toBe(bounds.min);
    expect(apply("End", false, 700)).toBe(bounds.max);
  });

  it("compounds on repeat instead of recomputing from one width", () => {
    const intent = resizeIntent("ArrowLeft", false);
    if (intent === null) throw new Error("ArrowLeft must resize");
    const once = applyResizeIntent(intent, 700, bounds);
    expect(applyResizeIntent(intent, once, bounds)).toBe(764);
  });

  it("ignores other keys", () => {
    expect(resizeIntent("Enter", false)).toBeNull();
  });
});
