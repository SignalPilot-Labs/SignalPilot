import { describe, expect, it } from "vitest";
import type { StandaloneChatEvent } from "~/lib/api";
import {
  buildChatNotebookPopoutUrl,
  deriveLiveNotebookLink,
} from "~/lib/chat-live-notebook";
import {
  FIXTURE_GATEWAY_SESSION_ID,
  FIXTURE_KERNEL_SESSION_ID,
  FIXTURE_NOTEBOOK_PATH,
  FIXTURE_RUN_ID,
  FIXTURE_TOTAL_MS,
  materializeFixtureEvents,
} from "~/lib/chat-test-fixture";

const RUN = "run-1";

function event(
  sequence: number,
  type: StandaloneChatEvent["type"],
  payload: Record<string, unknown> = {},
  runId = RUN,
): StandaloneChatEvent {
  return {
    run_id: runId,
    sequence,
    type,
    payload,
    created_at: new Date(1_700_000_000_000 + sequence * 1000).toISOString(),
  };
}

const startedPayload = {
  status: "running",
  gateway_session_id: "gw-1",
  kernel_session_id: "s_abc123",
  notebook_path: "/tmp/signalpilot-chat-runs/run-1/analysis.py",
};

describe("deriveLiveNotebookLink", () => {
  it("returns null with no runId or no notebook events", () => {
    expect(deriveLiveNotebookLink([], undefined)).toBeNull();
    expect(deriveLiveNotebookLink([], RUN)).toBeNull();
    expect(
      deriveLiveNotebookLink([event(1, "tool_started", { tool: "x" })], RUN),
    ).toBeNull();
  });

  it("ignores legacy notebook_started events without attach ids", () => {
    expect(
      deriveLiveNotebookLink([event(1, "notebook_started", { status: "running" })], RUN),
    ).toBeNull();
  });

  it("derives a live link from an enriched notebook_started", () => {
    const link = deriveLiveNotebookLink(
      [event(1, "notebook_started", startedPayload)],
      RUN,
    );
    expect(link).toEqual({
      runId: RUN,
      gatewaySessionId: "gw-1",
      kernelSessionId: "s_abc123",
      notebookPath: "/tmp/signalpilot-chat-runs/run-1/analysis.py",
      live: true,
    });
  });

  it("marks the link as not live after kernel_stopped", () => {
    const link = deriveLiveNotebookLink(
      [
        event(1, "notebook_started", startedPayload),
        event(2, "kernel_stopped", { status: "stopped" }),
      ],
      RUN,
    );
    expect(link?.live).toBe(false);
    expect(link?.kernelSessionId).toBe("s_abc123");
  });

  it("re-arms on a replacement kernel (notebook recovery)", () => {
    const link = deriveLiveNotebookLink(
      [
        event(1, "notebook_started", startedPayload),
        event(2, "kernel_stopped", { status: "stopped" }),
        event(3, "notebook_started", {
          ...startedPayload,
          kernel_session_id: "s_def456",
        }),
      ],
      RUN,
    );
    expect(link?.live).toBe(true);
    expect(link?.kernelSessionId).toBe("s_def456");
  });

  it("ignores events from other runs and sorts by sequence", () => {
    const link = deriveLiveNotebookLink(
      [
        event(9, "kernel_stopped", {}, "other-run"),
        event(2, "kernel_stopped", { status: "stopped" }),
        event(1, "notebook_started", startedPayload),
      ],
      RUN,
    );
    expect(link?.live).toBe(false);
  });
});

describe("buildChatNotebookPopoutUrl", () => {
  it("builds the /chat-notebook pop-out URL with attach params", () => {
    const url = buildChatNotebookPopoutUrl({
      runId: RUN,
      gatewaySessionId: "gw-1",
      kernelSessionId: "s_abc123",
      notebookPath: "/tmp/signalpilot-chat-runs/run-1/analysis.py",
      live: true,
    });
    expect(url.startsWith("/chat-notebook?")).toBe(true);
    const params = new URLSearchParams(url.split("?")[1]);
    expect(params.get("gw_session")).toBe("gw-1");
    expect(params.get("session_id")).toBe("s_abc123");
    expect(params.get("file")).toBe(
      "/tmp/signalpilot-chat-runs/run-1/analysis.py",
    );
  });
});

describe("fixture integration", () => {
  it("the fixture stream yields a live link after notebook_started", () => {
    const link = deriveLiveNotebookLink(
      materializeFixtureEvents(9_000),
      FIXTURE_RUN_ID,
    );
    expect(link).toEqual({
      runId: FIXTURE_RUN_ID,
      gatewaySessionId: FIXTURE_GATEWAY_SESSION_ID,
      kernelSessionId: FIXTURE_KERNEL_SESSION_ID,
      notebookPath: FIXTURE_NOTEBOOK_PATH,
      live: true,
    });
  });

  it("the fixture stream ends with a non-live link and an archive event", () => {
    const events = materializeFixtureEvents(FIXTURE_TOTAL_MS);
    const link = deriveLiveNotebookLink(events, FIXTURE_RUN_ID);
    expect(link?.live).toBe(false);
    expect(
      events.some((candidate) => candidate.type === "archive_completed"),
    ).toBe(true);
  });
});
