import { describe, expect, it } from "vitest";
import type { StandaloneChatEvent } from "~/lib/api";
import { extractConnectorSignInRequests } from "~/lib/chat-connector-signin";
import { connectorSignInFixtureEvents } from "~/lib/chat-connector-signin-fixture";
import { FIXTURE_RUN_ID, materializeFixtureEvents } from "~/lib/chat-test-fixture";

const ev = (
  sequence: number,
  type: StandaloneChatEvent["type"],
  payload: Record<string, unknown>,
  run_id = "run-1",
): StandaloneChatEvent => ({ run_id, sequence, type, payload, created_at: "2026-09-01T00:00:00Z" });

describe("extractConnectorSignInRequests", () => {
  it("finds the proxy's sign-in error and names the connector from the quoted text", () => {
    const events = [
      ev(1, "tool_started", { tool: "mcp__jira__search_issues", tool_call_id: "a" }),
      ev(2, "tool_completed", { tool_call_id: "a", error: true, summary: 'Connector "Jira" needs you to sign in again from Chat settings' }),
    ];
    expect(extractConnectorSignInRequests(events, "run-1")).toEqual([
      { connectorName: "Jira", slug: "jira", tool: "search_issues", sequence: 2 },
    ]);
  });
  it("falls back to the tool prefix when the message carries no quoted name", () => {
    const events = [
      ev(1, "tool_started", { tool: "mcp__snowflake_docs__search_docs", tool_call_id: "a" }),
      ev(2, "tool_completed", { tool_call_id: "a", error: true, message: "This connector needs you to sign in." }),
    ];
    expect(extractConnectorSignInRequests(events, "run-1")[0]).toMatchObject({
      connectorName: "Snowflake Docs",
      slug: "snowflake_docs",
    });
  });
  it("ignores ordinary tool errors, other runs, and successes", () => {
    const events = [
      ev(1, "tool_started", { tool: "mcp__jira__search_issues", tool_call_id: "a" }),
      ev(2, "tool_completed", { tool_call_id: "a", error: true, summary: "Upstream returned 502" }),
      ev(3, "tool_started", { tool: "mcp__jira__get_issue", tool_call_id: "b" }, "run-2"),
      ev(4, "tool_completed", { tool_call_id: "b", error: true, summary: 'Connector "Jira" needs you to sign in' }, "run-2"),
      ev(5, "tool_completed", { tool_call_id: "c", error: false, summary: 'Connector "Jira" needs you to sign in' }),
    ];
    expect(extractConnectorSignInRequests(events, "run-1")).toEqual([]);
  });
  it("dedupes retries of the same connector within a run", () => {
    const events = [
      ev(1, "tool_started", { tool: "mcp__jira__search_issues", tool_call_id: "a" }),
      ev(2, "tool_completed", { tool_call_id: "a", error: true, summary: 'Connector "Jira" needs you to sign in' }),
      ev(3, "tool_started", { tool: "mcp__jira__get_issue", tool_call_id: "b" }),
      ev(4, "tool_completed", { tool_call_id: "b", error: true, summary: 'Connector "Jira" needs you to sign in' }),
    ];
    expect(extractConnectorSignInRequests(events, "run-1")).toHaveLength(1);
  });
  it("pairs by FIFO when the worker sends no tool_call_id", () => {
    const events = [
      ev(1, "tool_started", { tool: "mcp__slack__search_messages" }),
      ev(2, "tool_completed", { error: true, summary: "Slack needs you to sign in again" }),
    ];
    expect(extractConnectorSignInRequests(events, "run-1")[0]).toMatchObject({ connectorName: "Slack", slug: "slack" });
  });
  it("is present in the /chats/test signin fixture from 3.75 s", () => {
    expect(extractConnectorSignInRequests(materializeFixtureEvents(3_000, connectorSignInFixtureEvents), FIXTURE_RUN_ID)).toEqual([]);
    expect(extractConnectorSignInRequests(materializeFixtureEvents(4_000, connectorSignInFixtureEvents), FIXTURE_RUN_ID)).toHaveLength(1);
  });
});
