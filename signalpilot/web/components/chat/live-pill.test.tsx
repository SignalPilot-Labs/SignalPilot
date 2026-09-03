import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { LivePill, livePillText } from "~/components/chat/live-pill";
import type { RunLiveInfo } from "~/lib/chat-run-steps";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const info = (
  state: RunLiveInfo["state"],
  label = "",
): RunLiveInfo => ({ state, label, step: null });

describe("LivePill", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("phrases each state as a present-tense line", () => {
    expect(livePillText(info("thinking", "Thinking"))).toBe("Thinking…");
    expect(livePillText(info("thinking", "Picking up your question"))).toBe(
      "Picking up your question…",
    );
    expect(livePillText(info("booting", "Starting secure runtime"))).toBe(
      "Starting runtime…",
    );
    expect(livePillText(info("tool", "Querying fct_orders"))).toBe(
      "Querying fct_orders…",
    );
    expect(livePillText(info("tool"))).toBe("Running a tool…");
    expect(livePillText(info("writing", "Writing"))).toBe("Writing…");
    expect(livePillText(info("idle"))).toBe("");
  });

  it("renders the state on the pill and nothing when idle", async () => {
    await act(async () => {
      root.render(<LivePill live={info("writing", "Writing")} />);
    });
    const pill = container.querySelector('[data-testid="chat-live-pill"]');
    expect(pill?.getAttribute("data-state")).toBe("writing");
    expect(pill?.textContent).toBe("Writing…");

    await act(async () => {
      root.render(<LivePill live={info("tool", "Running dbt")} />);
    });
    expect(
      container.querySelector('[data-testid="chat-live-pill"]')?.textContent,
    ).toBe("Running dbt…");

    await act(async () => {
      root.render(<LivePill live={info("idle")} />);
    });
    expect(container.querySelector('[data-testid="chat-live-pill"]')).toBeNull();
  });
});
