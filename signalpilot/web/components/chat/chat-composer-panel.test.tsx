import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatComposerPanel } from "~/components/chat/chat-composer-panel";
import { ChatUiContext } from "~/components/chat/chat-ui-context";
import type {
  StandaloneChatBootstrap,
  StandaloneChatEvent,
  StandaloneChatRun,
} from "~/lib/api";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const bootstrap = {
  enabled: true,
  projects: [],
  selected_project_id: null,
  enterprise_features: {},
} as unknown as StandaloneChatBootstrap;

const run = (status: StandaloneChatRun["status"]): StandaloneChatRun =>
  ({ id: "run-1", conversation_id: "conv-1", status }) as StandaloneChatRun;

const events: StandaloneChatEvent[] = [
  {
    run_id: "run-1",
    sequence: 2,
    type: "tool_started",
    payload: {
      tool: "TodoWrite",
      tool_call_id: "call-1",
      input: {
        todos: [
          { content: "Find the model", status: "completed" },
          { content: "Query it", status: "in_progress" },
        ],
      },
    },
    created_at: "2026-01-01T00:00:00Z",
  },
];

describe("ChatComposerPanel plan dock", () => {
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

  const render = async (
    currentRun: StandaloneChatRun | null,
    contextEvents: StandaloneChatEvent[],
  ) => {
    await act(async () => {
      root.render(
        <ChatUiContext.Provider
          value={{
            events: contextEvents,
            conversationId: currentRun ? "conv-1" : null,
            files: [],
            openArtifact: () => undefined,
            onStop: async () => undefined,
            onRetry: async () => undefined,
            onOpenDashboardPreview: () => undefined,
          }}
        >
          <ChatComposerPanel
            draft=""
            setDraft={vi.fn()}
            submitText={vi.fn(async () => undefined)}
            submitDisabled={false}
            disabledReason={undefined}
            runIsStreaming={currentRun?.status === "running"}
            currentRun={currentRun}
            onStop={vi.fn(async () => undefined)}
            mentionOptions={[]}
            conversationId={currentRun ? "conv-1" : undefined}
            bootstrap={bootstrap}
            selectedProjectId={null}
            onSelectProject={vi.fn()}
          />
        </ChatUiContext.Provider>,
      );
    });
  };
  const tracker = () =>
    container.querySelector('[data-testid="chat-plan-tracker"]');
  const expanded = () =>
    tracker()
      ?.querySelector("button[aria-expanded]")
      ?.getAttribute("aria-expanded");

  it("shows nothing on the empty new-chat page", async () => {
    await render(null, events);
    expect(tracker()).toBeNull();
  });

  it("shows nothing for a run without a plan", async () => {
    await render(run("running"), []);
    expect(tracker()).toBeNull();
  });

  it("derives the running run's plan from the context events, expanded", async () => {
    await render(run("running"), events);
    expect(tracker()?.textContent).toContain("1/2");
    expect(tracker()?.textContent).toContain("Query it");
    expect(expanded()).toBe("true");
  });

  it("keeps the latest run's final plan folded once it completes", async () => {
    await render(run("completed"), events);
    expect(tracker()?.textContent).toContain("1/2");
    expect(expanded()).toBe("false");
  });
});
