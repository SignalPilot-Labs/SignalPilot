import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatMessage } from "~/components/chat/chat-message";
import {
  ChatUiContext,
  type UiMessage,
} from "~/components/chat/chat-ui-context";

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
            artifacts: [],
            conversationId: null,
            files: [],
            openArtifact: () => undefined,
            onStop: async () => undefined,
            onRetry: async () => undefined,
            onApproveReportSuggestion: async () => ({ report_id: "report-1" }),
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
