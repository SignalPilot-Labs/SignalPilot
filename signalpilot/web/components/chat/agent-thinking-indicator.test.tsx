// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AgentThinkingIndicator,
  THINKING_PHRASES,
} from "./agent-thinking-indicator";

describe("AgentThinkingIndicator", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.useFakeTimers();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  function phrase(): string {
    return (
      container.querySelector('[data-testid="chat-thinking-phrase"]')
        ?.textContent ?? ""
    );
  }

  it("shows a phrase from the set and rotates it on the interval", () => {
    act(() => root.render(<AgentThinkingIndicator />));
    const first = phrase();
    expect(THINKING_PHRASES).toContain(first);
    const index = THINKING_PHRASES.indexOf(first as (typeof THINKING_PHRASES)[number]);
    act(() => {
      vi.advanceTimersByTime(2_400);
    });
    expect(phrase()).toBe(THINKING_PHRASES[(index + 1) % THINKING_PHRASES.length]);
    act(() => {
      vi.advanceTimersByTime(2_400 * THINKING_PHRASES.length);
    });
    expect(phrase()).toBe(THINKING_PHRASES[(index + 1) % THINKING_PHRASES.length]);
  });

  it("keeps the label and the thinking test id", () => {
    act(() => root.render(<AgentThinkingIndicator label="Picking up your question" />));
    const row = container.querySelector('[data-testid="chat-agent-thinking"]');
    expect(row?.textContent).toContain("Picking up your question");
  });
});
