import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatMessage } from "~/components/chat/chat-message";
import {
  ChatUiContext,
  type UiMessage,
} from "~/components/chat/chat-ui-context";
import type { ConversationFileInfo, StandaloneChatEvent } from "~/lib/api";

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

  it("never renders the plan tracker inside the message; it lives on the composer", async () => {
    const todoWrite: StandaloneChatEvent = {
      run_id: "run-1",
      sequence: 2,
      type: "tool_started",
      payload: {
        tool: "TodoWrite",
        tool_call_id: "call-plan",
        input: { todos: [{ content: "Find the model", status: "in_progress" }] },
      },
      created_at: "2026-01-01T00:00:00Z",
    };
    await render(message("running"), [todoWrite]);
    // The TodoWrite step still shows as a timeline card; only the tracker
    // itself moved to the composer.
    expect(
      container.querySelector('[data-testid="chat-plan-tracker"]'),
    ).toBeNull();
    expect(container.textContent).toContain("Updated the plan");
  });
});

describe("Data Chat artifact cards in the timeline", () => {
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

  const at = "2026-01-01T00:00:00Z";
  const fileRow = (path: string): ConversationFileInfo => ({
    id: `id-${path}`,
    path,
    filename: path.split("/").pop() ?? path,
    kind: "data",
    mime_type: "text/csv",
    byte_size: 64,
    content_hash: "h1",
    origin_run_id: "run-1",
    origin: "runtime",
    status: "active",
    created_at: at,
    updated_at: at,
  });
  // Narration first, then the tool chain, so the chain is the trailing
  // (open) group while the run streams.
  const events: StandaloneChatEvent[] = [
    {
      run_id: "run-1",
      sequence: 1,
      type: "text_delta",
      payload: { delta: "See [rows](artifacts/rows.csv) and ![gone](artifacts/gone.png)." },
      created_at: at,
    },
    {
      run_id: "run-1",
      sequence: 2,
      type: "tool_started",
      payload: {
        tool: "mcp__standalone-chat__run_cells",
        tool_call_id: "call-1",
        input: { cells: [{ source: "df.to_csv('artifacts/rows.csv')" }] },
      },
      created_at: at,
    },
    {
      run_id: "run-1",
      sequence: 3,
      type: "tool_completed",
      payload: { tool_call_id: "call-1", summary: "Executed 1 cell.", error: false },
      created_at: at,
    },
    {
      run_id: "run-1",
      sequence: 4,
      type: "files_changed",
      payload: {
        changed: 1,
        files: [{ path: "artifacts/rows.csv", kind: "data" }],
        tool_call_id: "call-1",
        origin: "runtime",
      },
      created_at: at,
    },
    // Run-end sweep: no tool_call_id, so this card has no step to sit under.
    {
      run_id: "run-1",
      sequence: 5,
      type: "files_changed",
      payload: {
        changed: 1,
        files: [{ path: "artifacts/sweep.csv", kind: "data" }],
        origin: "runtime",
      },
      created_at: at,
    },
  ];
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
  const render = async (msg: UiMessage) => {
    await act(async () => {
      root.render(
        <ChatUiContext.Provider
          value={{
            events,
            conversationId: "conv-1",
            files: [fileRow("artifacts/rows.csv"), fileRow("artifacts/sweep.csv")],
            openArtifact: () => undefined,
            onStop: async () => undefined,
            onRetry: async () => undefined,
            onOpenDashboardPreview: () => undefined,
          }}
        >
          <ChatMessage message={msg} />
        </ChatUiContext.Provider>,
      );
    });
  };

  it("anchors a card under the step that produced the file and trails the rest", async () => {
    await render(message("running"));
    // The run is live, so the group is open and the step row renders.
    const anchored = container.querySelector(
      '[data-testid="chat-step-artifact-cards"]',
    );
    expect(anchored?.getAttribute("data-anchor-sequence")).toBe("2");
    expect(anchored?.textContent).toContain("rows.csv");
    // The step row precedes its card inside the same list.
    const list = anchored?.closest("ol");
    const items = [...(list?.children ?? [])];
    expect(items.indexOf(anchored!.closest("li")!)).toBe(1);
    const trailing = container.querySelector(
      '[data-testid="chat-trailing-artifact-cards"]',
    );
    expect(trailing?.textContent).toContain("sweep.csv");
    expect(trailing?.textContent).not.toContain("rows.csv");
    // The inline chip and the timeline card are two surfaces; both show.
    expect(
      container.querySelector('[data-testid="chat-md-file-chip"]'),
    ).not.toBeNull();
    // No bottom-of-message block any more.
    expect(
      container.querySelectorAll('[data-testid="chat-artifact-cards"]'),
    ).toHaveLength(2);
  });

  it("hoists a collapsed group's cards into a visible footer once the run ends", async () => {
    await render(message("completed"));
    expect(
      container.querySelector('[data-testid="chat-step-artifact-cards"]'),
    ).toBeNull();
    const footer = container.querySelector(
      '[data-testid="chat-group-artifact-cards"]',
    );
    expect(footer?.textContent).toContain("rows.csv");
    expect(
      container.querySelector('[data-testid="chat-trailing-artifact-cards"]')
        ?.textContent,
    ).toContain("sweep.csv");
  });

  it("shows the missing image as a block band once the message's run ended", async () => {
    await render(message("completed"));
    const band = container.querySelector('[data-testid="chat-md-image-missing"]');
    expect(band?.getAttribute("role")).toBe("status");
    expect(band?.textContent).toContain("gone.png");
    expect(
      container.querySelector('[data-testid="chat-md-figure-pending"]'),
    ).toBeNull();
  });

  it("shows the pending placeholder only while the message's own run streams", async () => {
    await render(message("running"));
    expect(
      container.querySelector('[data-testid="chat-md-figure-pending"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="chat-md-image-missing"]'),
    ).toBeNull();
  });
});
