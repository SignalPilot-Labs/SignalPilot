import type { FixtureEvent } from "./chat-test-fixture-data";
import { FIXTURE_RUN_ID } from "./chat-test-fixture-data";

/**
 * Extra fixture events for /chats/test?signin=1: the agent calls a Jira
 * tool through the gateway proxy, the member's sign-in has expired, and the
 * proxy answers with the sign-in error the chat turns into a card.
 */
export const CONNECTOR_SIGN_IN_AT_MS = 3_300;

export const connectorSignInFixtureEvents: FixtureEvent[] = [
  {
    at: CONNECTOR_SIGN_IN_AT_MS,
    run_id: FIXTURE_RUN_ID,
    sequence: 901,
    type: "tool_started",
    payload: {
      tool: "mcp__jira__search_issues",
      tool_call_id: "t-connector-1",
      input: { jql: "project = DATA AND status = 'In Progress'" },
    },
  },
  {
    at: CONNECTOR_SIGN_IN_AT_MS + 450,
    run_id: FIXTURE_RUN_ID,
    sequence: 902,
    type: "tool_completed",
    payload: {
      tool_call_id: "t-connector-1",
      error: true,
      summary: 'Connector "Jira" needs you to sign in again from Chat settings',
    },
  },
];
