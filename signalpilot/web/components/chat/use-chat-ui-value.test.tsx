import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StandaloneChatEvent } from "~/lib/api";
import type {
  ChatUiContextValue,
  UiMessage,
} from "~/components/chat/chat-ui-context";

// Count activity-block renders per run: the costly subtree of a message.
const blockRenders = vi.hoisted(() => new Map<string, number>());
vi.mock("~/components/chat/run-timeline", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("~/components/chat/run-timeline")>();
  return {
    ...actual,
    RunActivityBlocks: (props: { blocks: { key: string }[] }) => {
      const key = props.blocks[0]?.key ?? "";
      const runId = /run-[ab]/.exec(key)?.[0] ?? "none";
      blockRenders.set(runId, (blockRenders.get(runId) ?? 0) + 1);
      return null;
    },
  };
});

import { ChatMessage } from "~/components/chat/chat-message";
import { ChatUiContext } from "~/components/chat/chat-ui-context";
import {
  useChatUiValue,
  useRunScopedChatUi,
  useStableMessages,
} from "~/components/chat/use-chat-ui-value";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function textEvent(runId: string, sequence: number): StandaloneChatEvent {
  return {
    run_id: runId,
    sequence,
    type: "text_delta",
    payload: { delta: `chunk ${sequence} ` },
    created_at: new Date(Date.UTC(2026, 8, 1, 0, 0, sequence)).toISOString(),
  };
}

function assistant(runId: string, status: string): UiMessage {
  return {
    id: `a-${runId}`,
    role: "assistant",
    content: "",
    sequence: 1,
    created_at: 1,
    metadata: { run_id: runId, status },
  };
}

const noop = async () => undefined;
const NO_FILES: ChatUiContextValue["files"] = [];
const openArtifact = () => undefined;

let setEvents: (next: (events: StandaloneChatEvent[]) => StandaloneChatEvent[]) => void =
  () => undefined;
let setDraft: (value: string) => void = () => undefined;

function Transcript({
  initialEvents,
  messages,
}: {
  initialEvents: StandaloneChatEvent[];
  messages: UiMessage[];
}) {
  const [events, updateEvents] = useState(initialEvents);
  const [draft, updateDraft] = useState("");
  setEvents = updateEvents;
  setDraft = updateDraft;
  const ui = useChatUiValue({
    events,
    conversationId: "c1",
    files: NO_FILES,
    openArtifact,
    onStop: noop,
    onRetry: noop,
  });
  const stable = useStableMessages(messages.map((message) => ({ ...message })));
  return (
    <ChatUiContext.Provider value={ui}>
      <span data-draft={draft} />
      {stable.map((message) => (
        <ChatMessage key={message.id} message={message} />
      ))}
    </ChatUiContext.Provider>
  );
}

describe("transcript render stability", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    blockRenders.clear();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("leaves a finished run alone while another run streams or the page re-renders", async () => {
    const finished = [1, 2, 3].map((sequence) => textEvent("run-a", sequence));
    const messages = [assistant("run-a", "completed"), assistant("run-b", "running")];
    await act(async () =>
      root.render(<Transcript initialEvents={finished} messages={messages} />),
    );
    const mountedA = blockRenders.get("run-a") ?? 0;
    expect(mountedA).toBeGreaterThan(0);

    for (let sequence = 1; sequence <= 5; sequence += 1) {
      await act(async () =>
        setEvents((events) => [...events, textEvent("run-b", sequence)]),
      );
    }
    for (let index = 0; index < 5; index += 1) {
      await act(async () => setDraft("x".repeat(index + 1)));
    }
    // A poll: every event arrives again as a fresh copy.
    await act(async () =>
      setEvents((events) => JSON.parse(JSON.stringify(events)) as StandaloneChatEvent[]),
    );

    expect(blockRenders.get("run-a")).toBe(mountedA);
    expect(blockRenders.get("run-b") ?? 0).toBeGreaterThan(0);
  });
});

describe("useRunScopedChatUi", () => {
  it("keeps the scoped value until its own run's events change", () => {
    const base: ChatUiContextValue = {
      events: [textEvent("run-a", 1)],
      conversationId: "c1",
      files: NO_FILES,
      openArtifact,
      onStop: noop,
      onRetry: noop,
    };
    const seen: ChatUiContextValue[] = [];
    function Probe({ ui }: { ui: ChatUiContextValue }) {
      seen.push(useRunScopedChatUi(ui, "run-a"));
      return null;
    }
    const container = document.createElement("div");
    const root = createRoot(container);
    act(() => root.render(<Probe ui={base} />));
    act(() =>
      root.render(
        <Probe ui={{ ...base, events: [...base.events, textEvent("run-b", 1)] }} />,
      ),
    );
    act(() =>
      root.render(
        <Probe ui={{ ...base, events: JSON.parse(JSON.stringify(base.events)) as StandaloneChatEvent[] }} />,
      ),
    );
    expect(seen[1]).toBe(seen[0]);
    expect(seen[2]).toBe(seen[0]);
    expect(seen[0]!.events.map((event) => event.run_id)).toEqual(["run-a"]);

    act(() =>
      root.render(
        <Probe ui={{ ...base, events: [...base.events, textEvent("run-a", 2)] }} />,
      ),
    );
    expect(seen[3]).not.toBe(seen[0]);
    expect(seen[3]!.events).toHaveLength(2);
    act(() => root.unmount());
  });
});
