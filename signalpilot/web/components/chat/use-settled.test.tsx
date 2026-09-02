import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSettled } from "~/components/chat/use-settled";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function Probe({ value }: { value: boolean }) {
  const settled = useSettled(value, 400);
  return <span data-settled={String(settled)} />;
}

describe("useSettled", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.useFakeTimers();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  const read = () => container.querySelector("span")?.getAttribute("data-settled");

  it("turns on at once and lingers for the delay after turning off", async () => {
    await act(async () => root.render(<Probe value={false} />));
    expect(read()).toBe("false");

    await act(async () => root.render(<Probe value={true} />));
    expect(read()).toBe("true");

    await act(async () => root.render(<Probe value={false} />));
    expect(read()).toBe("true");

    await act(async () => {
      vi.advanceTimersByTime(399);
    });
    expect(read()).toBe("true");

    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(read()).toBe("false");
  });

  it("cancels the pending drop when the value comes back on", async () => {
    await act(async () => root.render(<Probe value={true} />));
    await act(async () => root.render(<Probe value={false} />));
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    await act(async () => root.render(<Probe value={true} />));
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });
    expect(read()).toBe("true");
  });
});
