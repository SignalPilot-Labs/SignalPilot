import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { FileText } from "lucide-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RunStep } from "~/lib/chat-run-steps";
import type { ToolCardDefinition } from "./registry";
import {
  COMPLETION_HOLD_MS,
  useCardDensity,
  type CardDensityState,
} from "./use-card-density";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const def: ToolCardDefinition = {
  kind: "json",
  Icon: FileText,
  accent: "neutral",
  summarize: (step) => ({ title: step.title, stat: null, ok: true }),
  Running: () => null,
  Expanded: () => null,
};

const pinning: ToolCardDefinition = {
  ...def,
  stayOpenOnComplete: (_step, isLast) => isLast,
};

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

  it("runs, holds expanded on completion, then folds to compact", async () => {
    await render({ step: step("running"), def, isLastInGroup: true, groupLive: true });
    expect(latest?.density).toBe("running");
    await render({ step: step("succeeded"), def, isLastInGroup: true, groupLive: true });
    expect(latest?.density).toBe("expanded");
    await act(async () => {
      vi.advanceTimersByTime(COMPLETION_HOLD_MS - 1);
    });
    expect(latest?.density).toBe("expanded");
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(latest?.density).toBe("compact");
  });

  it("keeps a failed step expanded after the hold", async () => {
    await render({ step: step("running"), def, isLastInGroup: false, groupLive: true });
    await render({ step: step("failed"), def, isLastInGroup: false, groupLive: true });
    await act(async () => {
      vi.advanceTimersByTime(COMPLETION_HOLD_MS * 2);
    });
    expect(latest?.density).toBe("expanded");
  });

  it("mounts an already-complete step compact with no timers", async () => {
    await render({ step: step("succeeded"), def, isLastInGroup: true, groupLive: false });
    expect(latest?.density).toBe("compact");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("mounts an already-failed step expanded", async () => {
    await render({ step: step("failed"), def, isLastInGroup: true, groupLive: false });
    expect(latest?.density).toBe("expanded");
  });

  it("honours stayOpenOnComplete only while the group is live", async () => {
    await render({ step: step("running"), def: pinning, isLastInGroup: true, groupLive: true });
    await render({ step: step("succeeded"), def: pinning, isLastInGroup: true, groupLive: true });
    await act(async () => {
      vi.advanceTimersByTime(COMPLETION_HOLD_MS);
    });
    expect(latest?.density).toBe("expanded");
    await render({ step: step("succeeded"), def: pinning, isLastInGroup: true, groupLive: false });
    expect(latest?.density).toBe("compact");
  });

  it("toggles by hand and re-opens on a focus request", async () => {
    await render({ step: step("succeeded"), def, isLastInGroup: true, groupLive: false });
    await act(async () => latest?.toggle());
    expect(latest?.density).toBe("expanded");
    await act(async () => latest?.toggle());
    expect(latest?.density).toBe("compact");
    await render({ step: step("succeeded"), def, isLastInGroup: true, groupLive: false, focusRequested: 1 });
    expect(latest?.density).toBe("expanded");
  });

  it("clears the user toggle when the step re-enters running", async () => {
    await render({ step: step("succeeded"), def, isLastInGroup: true, groupLive: false });
    await act(async () => latest?.setOpen(true));
    expect(latest?.density).toBe("expanded");
    await render({ step: step("running"), def, isLastInGroup: true, groupLive: true });
    expect(latest?.density).toBe("running");
    await render({ step: step("succeeded"), def, isLastInGroup: true, groupLive: true });
    await act(async () => {
      vi.advanceTimersByTime(COMPLETION_HOLD_MS);
    });
    expect(latest?.density).toBe("compact");
  });
});
