import { describe, expect, it } from "vitest";
import type { ConversationNotebook, StandaloneChatEvent } from "~/lib/api";
import {
  buildChatNotebookPopoutUrl,
  canAttachLive,
  chatNotebookMountKey,
  hasNotebookContent,
  notebookRefreshRevision,
  pickDefaultNotebook,
} from "~/lib/chat-live-notebook";
import {
  FIXTURE_GATEWAY_SESSION_ID,
  FIXTURE_KERNEL_SESSION_ID,
  FIXTURE_NOTEBOOK_PATH,
  FIXTURE_TOTAL_MS,
  fixtureConversationNotebook,
  fixtureConversationNotebooks,
  materializeFixtureEvents,
} from "~/lib/chat-test-fixture";

function event(
  sequence: number,
  type: StandaloneChatEvent["type"],
  payload: Record<string, unknown> = {},
): StandaloneChatEvent {
  return {
    run_id: "run-1",
    sequence,
    type,
    payload,
    created_at: new Date(1_700_000_000_000 + sequence * 1000).toISOString(),
  };
}

function notebook(
  overrides: Partial<ConversationNotebook> = {},
): ConversationNotebook {
  return {
    name: "analysis",
    status: "live",
    gateway_session_id: "gw-1",
    kernel_session_id: "s_abc123",
    notebook_path: "/tmp/signalpilot-chat-runs/run-1/analysis.py",
    document: null,
    ...overrides,
  };
}

describe("notebookRefreshRevision", () => {
  it("counts only notebook-related events", () => {
    expect(notebookRefreshRevision([])).toBe(0);
    expect(
      notebookRefreshRevision([
        event(1, "tool_started", { tool: "x" }),
        event(2, "text_delta", { delta: "hi" }),
      ]),
    ).toBe(0);
    expect(
      notebookRefreshRevision([
        event(1, "notebook_started"),
        event(2, "tool_started", { tool: "x" }),
        event(3, "archive_completed"),
        event(4, "kernel_stopped"),
      ]),
    ).toBe(3);
  });
});

describe("canAttachLive", () => {
  it("requires live status and all attach ids", () => {
    expect(canAttachLive(null)).toBe(false);
    expect(canAttachLive(notebook())).toBe(true);
    expect(canAttachLive(notebook({ status: "ended" }))).toBe(false);
    expect(canAttachLive(notebook({ kernel_session_id: null }))).toBe(false);
    expect(canAttachLive(notebook({ notebook_path: null }))).toBe(false);
  });
});

describe("hasNotebookContent", () => {
  it("is false for null and status none", () => {
    expect(hasNotebookContent(null)).toBe(false);
    expect(
      hasNotebookContent(
        notebook({ status: "none", gateway_session_id: null }),
      ),
    ).toBe(false);
  });

  it("is true for a live notebook without a document", () => {
    expect(hasNotebookContent(notebook())).toBe(true);
  });

  it("is true for an ended notebook with a saved document", () => {
    expect(
      hasNotebookContent(
        notebook({
          status: "ended",
          document: { source: "code", session: null },
        }),
      ),
    ).toBe(true);
  });

  it("is false for an ended notebook without a saved document", () => {
    expect(hasNotebookContent(notebook({ status: "ended" }))).toBe(false);
  });
});

describe("buildChatNotebookPopoutUrl", () => {
  it("builds the /chat-notebook pop-out URL for a conversation", () => {
    const url = buildChatNotebookPopoutUrl("conv-1");
    expect(url.startsWith("/chat-notebook?")).toBe(true);
    const params = new URLSearchParams(url.split("?")[1]);
    expect(params.get("conversation")).toBe("conv-1");
    expect(params.get("notebook")).toBe(null);
  });

  it("omits the notebook param for the default analysis notebook", () => {
    const url = buildChatNotebookPopoutUrl("conv-1", "analysis");
    const params = new URLSearchParams(url.split("?")[1]);
    expect(params.get("notebook")).toBe(null);
  });

  it("carries a non-default notebook name", () => {
    const url = buildChatNotebookPopoutUrl("conv-1", "forecast");
    const params = new URLSearchParams(url.split("?")[1]);
    expect(params.get("conversation")).toBe("conv-1");
    expect(params.get("notebook")).toBe("forecast");
  });
});

describe("pickDefaultNotebook", () => {
  it("returns null for an empty list", () => {
    expect(pickDefaultNotebook([])).toBe(null);
  });

  it("prefers the analysis entry regardless of order", () => {
    const forecast = notebook({ name: "forecast" });
    const analysis = notebook();
    expect(pickDefaultNotebook([forecast, analysis])).toBe(analysis);
  });

  it("falls back to the first entry without an analysis notebook", () => {
    const forecast = notebook({ name: "forecast" });
    const scratch = notebook({ name: "scratch" });
    expect(pickDefaultNotebook([forecast, scratch])).toBe(forecast);
  });
});

describe("chatNotebookMountKey", () => {
  it("changes when liveness or the attach target changes", () => {
    const base = chatNotebookMountKey(notebook());
    expect(chatNotebookMountKey(notebook())).toBe(base);
    expect(chatNotebookMountKey(notebook({ status: "ended" }))).not.toBe(base);
    expect(
      chatNotebookMountKey(notebook({ kernel_session_id: "s_other" })),
    ).not.toBe(base);
  });

  it("changes when the notebook name changes", () => {
    const base = chatNotebookMountKey(notebook());
    expect(chatNotebookMountKey(notebook({ name: "forecast" }))).not.toBe(base);
  });
});

describe("fixture integration", () => {
  it("simulates a live resource after notebook_started", () => {
    const resource = fixtureConversationNotebook(
      materializeFixtureEvents(9_000),
    );
    expect(resource).toEqual({
      name: "analysis",
      status: "live",
      gateway_session_id: FIXTURE_GATEWAY_SESSION_ID,
      kernel_session_id: FIXTURE_KERNEL_SESSION_ID,
      notebook_path: FIXTURE_NOTEBOOK_PATH,
      document: null,
    });
  });

  it("simulates an ended resource with a document after kernel_stopped", () => {
    const resource = fixtureConversationNotebook(
      materializeFixtureEvents(FIXTURE_TOTAL_MS),
    );
    expect(resource?.status).toBe("ended");
    expect(resource?.document?.source).toContain("Q3 regional growth");
    expect(hasNotebookContent(resource ?? null)).toBe(true);
  });

  it("returns null before any notebook starts", () => {
    expect(fixtureConversationNotebook(materializeFixtureEvents(1_000))).toBe(
      null,
    );
  });

  it("lists one notebook mid-run and two after the archive lands", () => {
    expect(
      fixtureConversationNotebooks(materializeFixtureEvents(9_000)).map(
        (entry) => entry.name,
      ),
    ).toEqual(["analysis"]);
    const final = fixtureConversationNotebooks(
      materializeFixtureEvents(FIXTURE_TOTAL_MS),
    );
    expect(final.map((entry) => entry.name)).toEqual(["analysis", "forecast"]);
    expect(final.every((entry) => hasNotebookContent(entry))).toBe(true);
    expect(pickDefaultNotebook(final)?.name).toBe("analysis");
  });
});
