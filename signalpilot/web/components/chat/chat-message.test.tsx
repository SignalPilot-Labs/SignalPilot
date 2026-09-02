import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatMessage } from "~/components/chat/chat-message";
import {
  ChatUiContext,
  type UiMessage,
} from "~/components/chat/chat-ui-context";
import type { StandaloneChatEvent } from "~/lib/api";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

describe("Data Chat dashboard artifact card", () => {
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
    vi.clearAllMocks();
  });

  it("renders a compact dashboard artifact and opens its governed preview", async () => {
    const onOpenDashboardPreview = vi.fn();
    const message: UiMessage = {
      id: "assistant-1",
      role: "assistant",
      content: "Your dashboard is ready.",
      sequence: 1,
      created_at: 0,
      metadata: {
        dashboard_preview: {
          authoring_session_id: "session-1",
          preview_url: "/dashboards/new?authoring=session-1",
          dashboard_name: "Sales overview",
          summary: "A concise view of sales performance.",
          chart_count: 3,
        },
      },
      runStatus: "completed",
    };

    await act(async () => {
      root.render(
        <ChatUiContext.Provider
          value={{
            events: [],
            conversationId: null,
            files: [],
            runningRunId: null,
            openArtifact: () => undefined,
            onStop: async () => undefined,
            onRetry: async () => undefined,
            onOpenDashboardPreview,
          }}
        >
          <ChatMessage message={message} />
        </ChatUiContext.Provider>,
      );
    });

    const card = container.querySelector(
      '[data-testid="dashboard-artifact-card"]',
    );
    expect(card?.textContent).toContain("Dashboard");
    expect(card?.textContent).toContain("Sales overview");
    expect(card?.textContent).toContain("3 charts · Draft ready for review");
    expect(card?.textContent).not.toContain("Nothing is saved");

    const viewButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="View Sales overview"]',
    );
    await act(async () => viewButton?.click());
    expect(onOpenDashboardPreview).toHaveBeenCalledWith("session-1");
  });
});

describe("Data Chat live state", () => {
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

  const render = async (message: UiMessage, events: StandaloneChatEvent[]) => {
    await act(async () => {
      root.render(
        <ChatUiContext.Provider
          value={{
            events,
            conversationId: null,
            files: [],
            runningRunId: null,
            openArtifact: () => undefined,
            onStop: async () => undefined,
            onRetry: async () => undefined,
            onOpenDashboardPreview: () => undefined,
          }}
        >
          <ChatMessage message={message} />
        </ChatUiContext.Provider>,
      );
    });
  };

  const textDelta: StandaloneChatEvent = {
    run_id: "run-1",
    sequence: 1,
    type: "text_delta",
    payload: { delta: "Three marts reference net_revenue." },
    created_at: "2026-01-01T00:00:00Z",
  };

  const message = (runStatus: UiMessage["runStatus"]): UiMessage => ({
    id: "assistant-1",
    role: "assistant",
    content: "",
    sequence: 1,
    created_at: 0,
    metadata: {},
    runId: "run-1",
    runStatus,
  });

  it("shows the writing pill, the stop ring and the caret while text streams", async () => {
    await render(message("running"), [textDelta]);
    const pill = container.querySelector('[data-testid="chat-live-pill"]');
    expect(pill?.textContent).toContain("Writing");
    expect(pill?.getAttribute("data-state")).toBe("writing");
    expect(
      container.querySelector(".chat-stop-ring")?.getAttribute("data-state"),
    ).toBe("writing");
    const caretHost = container.querySelector('[data-caret="true"]');
    expect(caretHost?.querySelector(".chat-markdown")).not.toBeNull();
    // Writing lives in the footer pill, never as an inline indicator.
    expect(
      container.querySelector('[data-testid="chat-live-indicator"]'),
    ).toBeNull();
  });

  it("shows the inline thinking indicator before any text arrives", async () => {
    await render(message("running"), []);
    const indicator = container.querySelector(
      '[data-testid="chat-live-indicator"]',
    );
    expect(indicator?.getAttribute("data-state")).toBe("thinking");
    expect(
      indicator?.querySelector('[data-testid="chat-agent-thinking"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="chat-live-pill"]')?.textContent,
    ).toBe("Thinking…");
  });

  it("drops the pill, ring and caret once the run completes", async () => {
    await render(message("completed"), [textDelta]);
    expect(container.querySelector('[data-testid="chat-live-pill"]')).toBeNull();
    expect(container.querySelector(".chat-stop-ring")).toBeNull();
    expect(container.querySelector("[data-caret]")).toBeNull();
    expect(container.querySelector(".chat-markdown")).not.toBeNull();
  });
});
