import type { StandaloneChatEvent } from "~/lib/api";

/**
 * Detects connector sign-in failures in a run's event stream. The gateway
 * proxy answers a tool call on a connector whose sign-in expired with a
 * JSON-RPC error whose message reads `Connector "<name>" needs you to sign
 * in again from Chat settings`; the worker surfaces it as a failed
 * tool_completed. One request per connector per run, so the chat shows one
 * card even when the agent retried.
 */
export type ConnectorSignInRequest = {
  /** Display name from the error text, or a title-cased slug fallback. */
  connectorName: string;
  /** The `mcp__<slug>__` prefix's slug when the tool name carried one. */
  slug: string | null;
  tool: string | null;
  sequence: number;
};

const NEEDS_SIGN_IN = /needs you to sign in/i;
const QUOTED_NAME = /connector\s+["“]([^"”]+)["”]\s+needs you to sign in/i;
const BARE_NAME = /^\s*([A-Za-z][\w .-]{0,60}?)\s+needs you to sign in/i;
const MCP_TOOL = /^mcp__([a-z0-9_]+)__(.+)$/;

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function titleFromSlug(slug: string): string {
  return slug
    .split("_")
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

export function extractConnectorSignInRequests(
  events: StandaloneChatEvent[],
  runId: string,
): ConnectorSignInRequest[] {
  const toolsByCallId = new Map<string, string>();
  const pendingTools: string[] = [];
  const seen = new Map<string, ConnectorSignInRequest>();
  for (const event of events) {
    if (event.run_id !== runId) continue;
    if (event.type === "tool_started") {
      const tool = text(event.payload.tool);
      const callId = text(event.payload.tool_call_id);
      if (tool && callId) toolsByCallId.set(callId, tool);
      else if (tool) pendingTools.push(tool);
      continue;
    }
    if (event.type !== "tool_completed" || event.payload.error !== true) continue;
    const message =
      text(event.payload.summary) ?? text(event.payload.message) ?? text(event.payload.error_message);
    if (!message || !NEEDS_SIGN_IN.test(message)) continue;
    const callId = text(event.payload.tool_call_id);
    const tool = (callId && toolsByCallId.get(callId)) ?? pendingTools.shift() ?? null;
    const mcp = tool ? MCP_TOOL.exec(tool) : null;
    const slug = mcp?.[1] ?? null;
    const bare = BARE_NAME.exec(message)?.[1]?.trim();
    const name =
      QUOTED_NAME.exec(message)?.[1]?.trim() ??
      (bare && !/^(this|the|your|a)\s+connector$/i.test(bare) ? bare : null) ??
      (slug ? titleFromSlug(slug) : null);
    if (!name) continue;
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.set(key, { connectorName: name, slug, tool: mcp?.[2] ?? tool, sequence: event.sequence });
  }
  return [...seen.values()];
}
