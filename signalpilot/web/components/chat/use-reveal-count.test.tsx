import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MAX_REVEAL_BACKLOG, REVEAL_INTERVAL_MS, useRevealCount } from "./use-reveal-count";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

describe("useRevealCount", () => {
  let container: HTMLDivElement;
  let root: Root;
  let shown = -1;
  function Probe({ total, live }: { total: number; live: boolean }) {
    shown = useRevealCount(total, live);
    return null;
  }
  const render = async (total: number, live: boolean) => {
    await act(async () => root.render(createElement(Probe, { total, live })));
  };
  beforeEach(() => {
    vi.useFakeTimers();
    container = document.createElement("div");
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    vi.useRealTimers();
  });

  it("shows everything present at mount at once", async () => {
    await render(4, true);
    expect(shown).toBe(4);
  });

  it("paces new items in one at a time while live", async () => {
    await render(1, true);
    await render(4, true);
    expect(shown).toBe(1);
    await act(async () => vi.advanceTimersByTime(REVEAL_INTERVAL_MS));
    expect(shown).toBe(2);
    // Each reveal schedules the next after it renders.
    await act(async () => vi.advanceTimersByTime(REVEAL_INTERVAL_MS));
    await act(async () => vi.advanceTimersByTime(REVEAL_INTERVAL_MS));
    expect(shown).toBe(4);
  });

  it("skips ahead on a long backlog and shows all when not live", async () => {
    await render(0, true);
    await render(20, true);
    await act(async () => vi.advanceTimersByTime(0));
    expect(shown).toBe(20 - MAX_REVEAL_BACKLOG);
    await render(20, false);
    expect(shown).toBe(20);
  });
});
