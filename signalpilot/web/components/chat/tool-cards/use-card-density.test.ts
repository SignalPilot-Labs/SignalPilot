import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RunStep } from "~/lib/chat-run-steps";
import { useCardDensity, type CardDensityState } from "./use-card-density";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function step(status: RunStep["status"]): RunStep {
  return {
    key: "s1",
    sequence: 1,
    category: "generic",
    status,
    title: "Inspected the dbt project",
    tool: "inspect_dbt",
    toolOrigin: "signalpilot",
    input: null,
    sql: null,
    code: null,
    file: null,
    sources: [],
    detail: null,
    result: null,
    startedAt: "2026-09-01T12:00:00.000Z",
    endedAt: status === "running" ? null : "2026-09-01T12:00:01.000Z",
    durationMs: status === "running" ? null : 1_000,
    children: [],
    subagentType: null,
    report: null,
    liveText: "",
  };
}

type Props = Parameters<typeof useCardDensity>[0];

describe("useCardDensity", () => {
  let container: HTMLDivElement;
  let root: Root;
  let latest: CardDensityState | null;

  function Probe(props: Props) {
    latest = useCardDensity(props);
    return null;
  }
  const render = async (props: Props) => {
    await act(async () => {
      root.render(createElement(Probe, props));
    });
  };

  beforeEach(() => {
    vi.useFakeTimers();
    latest = null;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  it("never opens on its own through running, done or failed", async () => {
    await render({ step: step("running") });
    expect(latest?.density).toBe("running");
    expect(latest?.open).toBe(false);
    await render({ step: step("succeeded") });
    expect(latest?.density).toBe("compact");
    await render({ step: step("running") });
    await render({ step: step("failed") });
    expect(latest?.density).toBe("compact");
    expect(latest?.open).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("toggles by hand and opens on a focus request", async () => {
    await render({ step: step("succeeded") });
    await act(async () => latest?.toggle());
    expect(latest?.density).toBe("expanded");
    await act(async () => latest?.toggle());
    expect(latest?.density).toBe("compact");
    await render({ step: step("succeeded"), focusRequested: 1 });
    expect(latest?.density).toBe("expanded");
  });

  it("keeps a hand-opened card open when its step finishes", async () => {
    await render({ step: step("running") });
    await act(async () => latest?.setOpen(true));
    await render({ step: step("succeeded") });
    expect(latest?.density).toBe("expanded");
  });
});
