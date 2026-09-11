import { describe, expect, it } from "vitest";

import {
  CANVAS_RESERVE,
  INSPECTOR_MIN_WIDTH,
  INSPECTOR_WIDTH_KEY,
  KEY_STEP,
  KEY_STEP_LARGE,
  LEFT_RAIL_WIDTH,
  PAGE_DEFAULT_WIDTH,
  clampWidth,
  defaultInspectorWidth,
  isWide,
  keyboardResize,
  leftPanelCollapses,
  parseStoredWidth,
  readStoredWidth,
  wideInspectorWidth,
  widthBounds,
  widthFittingPanel,
  writeStoredWidth,
} from "./inspector-resize";

class MemoryStorage {
  map = new Map<string, string>();
  getItem(k: string) {
    return this.map.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    this.map.set(k, v);
  }
  removeItem(k: string) {
    this.map.delete(k);
  }
}

describe("widthBounds and clampWidth", () => {
  it("leaves the canvas reserve plus the rail at the maximum", () => {
    const b = widthBounds(1600);
    expect(b.min).toBe(INSPECTOR_MIN_WIDTH);
    expect(b.max).toBe(1600 - CANVAS_RESERVE - LEFT_RAIL_WIDTH);
  });

  it("never drops the maximum under the minimum on tiny viewports", () => {
    expect(widthBounds(400).max).toBe(INSPECTOR_MIN_WIDTH);
  });

  it("is unbounded before the container is measured", () => {
    const b = widthBounds(0);
    expect(b.max).toBe(Number.POSITIVE_INFINITY);
    expect(clampWidth(2000, b)).toBe(2000);
  });

  it("clamps, rounds, and rejects non-finite widths", () => {
    const b = widthBounds(1600);
    expect(clampWidth(100, b)).toBe(b.min);
    expect(clampWidth(5000, b)).toBe(b.max);
    expect(clampWidth(600.4, b)).toBe(600);
    expect(clampWidth(Number.NaN, b)).toBe(b.min);
  });
});

describe("defaults and presets", () => {
  it("uses a fixed page default and a share of the modal", () => {
    expect(defaultInspectorWidth("page", 1600)).toBe(PAGE_DEFAULT_WIDTH);
    expect(defaultInspectorWidth("page", 0)).toBe(PAGE_DEFAULT_WIDTH);
    expect(defaultInspectorWidth("modal", 1000)).toBe(450);
    expect(defaultInspectorWidth("modal", 0)).toBe(PAGE_DEFAULT_WIDTH);
  });

  it("the default never collapses the full left panel", () => {
    // 1056 wide row with the 288 focus panel: 560 would squeeze the canvas.
    expect(defaultInspectorWidth("page", 1056, 288)).toBe(1056 - 288 - CANVAS_RESERVE);
    expect(defaultInspectorWidth("page", 1600, 288)).toBe(PAGE_DEFAULT_WIDTH);
    expect(leftPanelCollapses(1056, defaultInspectorWidth("page", 1056, 288), 288)).toBe(false);
    // Tiny rows bottom out at the minimum.
    expect(defaultInspectorWidth("page", 700, 288)).toBe(INSPECTOR_MIN_WIDTH);
  });

  it("the wide preset is 70 percent, clamped to the bounds", () => {
    expect(wideInspectorWidth(1600)).toBe(1120);
    expect(wideInspectorWidth(500)).toBe(INSPECTOR_MIN_WIDTH);
    expect(isWide(1120, 1600)).toBe(true);
    expect(isWide(1000, 1600)).toBe(false);
    expect(isWide(1000, 0)).toBe(false);
  });

  it("the left panel collapses once the canvas would go under the reserve", () => {
    expect(leftPanelCollapses(1600, 560, 288)).toBe(false);
    expect(leftPanelCollapses(1600, 1100, 288)).toBe(true);
    expect(leftPanelCollapses(0, 1100, 288)).toBe(false);
    const fit = widthFittingPanel(1600, 288);
    expect(fit).toBe(1600 - 288 - CANVAS_RESERVE);
    expect(leftPanelCollapses(1600, fit, 288)).toBe(false);
  });
});

describe("persistence", () => {
  it("parses stored values and ignores junk", () => {
    expect(parseStoredWidth("640")).toBe(640);
    expect(parseStoredWidth("640.6")).toBe(641);
    expect(parseStoredWidth("abc")).toBeNull();
    expect(parseStoredWidth("12")).toBeNull();
    expect(parseStoredWidth(null)).toBeNull();
  });

  it("round-trips through storage under the shared key and clears on null", () => {
    const s = new MemoryStorage();
    writeStoredWidth(s, 720.4);
    expect(s.getItem(INSPECTOR_WIDTH_KEY)).toBe("720");
    expect(readStoredWidth(s)).toBe(720);
    writeStoredWidth(s, null);
    expect(readStoredWidth(s)).toBeNull();
  });

  it("swallows storage failures", () => {
    const broken = {
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
    expect(readStoredWidth(broken)).toBeNull();
    expect(() => writeStoredWidth(broken, 500)).not.toThrow();
    expect(readStoredWidth(null)).toBeNull();
  });
});

describe("keyboardResize", () => {
  const b = widthBounds(1600);

  it("left widens and right narrows by the step, shift by the big step", () => {
    expect(keyboardResize("ArrowLeft", false, 560, b)).toBe(560 + KEY_STEP);
    expect(keyboardResize("ArrowRight", false, 560, b)).toBe(560 - KEY_STEP);
    expect(keyboardResize("ArrowLeft", true, 560, b)).toBe(560 + KEY_STEP_LARGE);
    expect(keyboardResize("ArrowRight", true, 560, b)).toBe(560 - KEY_STEP_LARGE);
  });

  it("clamps at the bounds and snaps with Home and End", () => {
    expect(keyboardResize("ArrowRight", true, INSPECTOR_MIN_WIDTH + 10, b)).toBe(INSPECTOR_MIN_WIDTH);
    expect(keyboardResize("ArrowLeft", true, b.max - 10, b)).toBe(b.max);
    expect(keyboardResize("Home", false, 900, b)).toBe(b.min);
    expect(keyboardResize("End", false, 900, b)).toBe(b.max);
    expect(keyboardResize("End", false, 900, widthBounds(0))).toBe(900);
  });

  it("ignores other keys", () => {
    expect(keyboardResize("ArrowUp", false, 560, b)).toBeNull();
    expect(keyboardResize("Enter", false, 560, b)).toBeNull();
  });
});
