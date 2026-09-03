// State for the three-step add flow. Kept as plain data + reducers so the
// modal stays a thin orchestrator and the steps stay presentational.

import type {
  ConnectorCreate,
  ConnectorScope,
  ProbeResult,
  ToolInfo,
} from "~/lib/api/mcp-connectors";
import {
  defaultToolSetting,
  parseServerInput,
  suggestName,
  type ServerInput,
} from "~/lib/mcp-connectors-state";

export type AddStep = 1 | 2 | 3 | "done";
export type AccessKind = "none" | "oauth" | "key";
export type EnvRow = { name: string; value: string; secret: boolean; member_supplied: boolean };

export type AddFlowState = {
  step: AddStep;
  raw: string;
  /** "auto" follows the parser; the user can pin a mode. */
  mode: "auto" | "url" | "command";
  probe: ProbeResult | null;
  probing: boolean;
  /** Probe failed: the user chose to keep going anyway. */
  saveAnyway: boolean;
  name: string;
  scope: ConnectorScope;
  access: AccessKind;
  headerName: string;
  headerValue: string;
  /** Org key connectors: each member enters their own value. */
  memberSupplied: boolean;
  env: EnvRow[];
  clientId: string;
  clientSecret: string;
  tools: ToolInfo[];
  submitting: boolean;
  error: string | null;
};

export function initialAddFlowState(scope: ConnectorScope): AddFlowState {
  return {
    step: 1,
    raw: "",
    mode: "auto",
    probe: null,
    probing: false,
    saveAnyway: false,
    name: "",
    scope,
    access: "none",
    headerName: "Authorization",
    headerValue: "",
    memberSupplied: false,
    env: [],
    clientId: "",
    clientSecret: "",
    tools: [],
    submitting: false,
    error: null,
  };
}

/** What the parser sees, honoring a pinned mode. */
export function resolveInput(state: Pick<AddFlowState, "raw" | "mode">): ServerInput {
  const parsed = parseServerInput(state.raw);
  if (state.mode === "auto" || parsed.kind === "empty" || parsed.kind === "invalid") return parsed;
  if (state.mode === "url" && parsed.kind === "command") {
    const text = state.raw.trim();
    return /^[a-z0-9.-]+(\/|$)/i.test(text)
      ? { kind: "url", url: `https://${text}` }
      : { kind: "invalid", reason: "That doesn't look like an address." };
  }
  if (state.mode === "command" && parsed.kind === "url") {
    return { kind: "command", command: state.raw.trim(), args: [] };
  }
  return parsed;
}

/** Apply a probe result: pick access, seed tools with R3 defaults, suggest a name. */
export function applyProbe(state: AddFlowState, probe: ProbeResult): AddFlowState {
  const input = resolveInput(state);
  const access: AccessKind =
    probe.auth === "oauth" ? "oauth" : probe.auth === "key" ? "key" : "none";
  const tools = (probe.tools ?? []).map((tool) => ({
    ...tool,
    ...defaultToolSetting(tool.annotations),
  }));
  const envSeed: EnvRow[] =
    input.kind === "command" && state.env.length === 0
      ? guessEnvRows(input.command, input.args, state.scope)
      : state.env;
  return {
    ...state,
    probe,
    probing: false,
    access: probe.error ? state.access : access,
    name: state.name || suggestName(input, probe.server_name),
    headerName: state.headerName,
    tools,
    env: envSeed,
    error: null,
  };
}

/** Well-known servers announce their env var in the package name. */
function guessEnvRows(command: string, args: string[], scope: ConnectorScope): EnvRow[] {
  const joined = [command, ...args].join(" ");
  const member = scope === "org";
  if (/server-github|github-mcp/.test(joined)) {
    return [{ name: "GITHUB_PERSONAL_ACCESS_TOKEN", value: "", secret: true, member_supplied: member }];
  }
  if (/server-slack/.test(joined)) {
    return [{ name: "SLACK_BOT_TOKEN", value: "", secret: true, member_supplied: member }];
  }
  return [];
}

export function toggleTool(state: AddFlowState, name: string, enabled: boolean): AddFlowState {
  return {
    ...state,
    tools: state.tools.map((tool) =>
      tool.name === name ? { ...tool, enabled, policy: enabled ? "auto" : "off" } : tool,
    ),
  };
}

/** The create payload. Secrets only travel here, never back. */
export function buildCreate(state: AddFlowState): ConnectorCreate {
  const input = resolveInput(state);
  const body: ConnectorCreate = { scope: state.scope, name: state.name.trim() };
  if (input.kind === "url") body.url = input.url;
  if (input.kind === "command") {
    body.command = input.command;
    body.args = input.args;
    body.transport = "stdio";
    body.env = state.env
      .filter((row) => row.name.trim())
      .map((row) => ({
        name: row.name.trim(),
        value: row.member_supplied || !row.value ? undefined : row.value,
        secret: row.secret,
        member_supplied: row.member_supplied,
      }));
  }
  if (state.probe?.transport && input.kind === "url") body.transport = state.probe.transport;
  body.auth = state.access;
  if (state.access === "key" && input.kind === "url" && state.headerValue && !state.memberSupplied) {
    body.headers = { [state.headerName.trim() || "Authorization"]: state.headerValue };
  }
  if (state.access === "oauth" && state.clientId.trim()) {
    body.oauth_client = {
      client_id: state.clientId.trim(),
      client_secret: state.clientSecret || undefined,
    };
  }
  return body;
}

/** Tool settings to PUT right after create (the create body carries none). */
export function buildToolSettings(
  state: AddFlowState,
): Record<string, { enabled: boolean; policy: "auto" | "off" }> {
  const next: Record<string, { enabled: boolean; policy: "auto" | "off" }> = {};
  for (const tool of state.tools) {
    next[tool.name] = tool.enabled ? { enabled: true, policy: "auto" } : { enabled: false, policy: "off" };
  }
  return next;
}

/** Step gating: what blocks "Continue" on each step. */
export function stepBlocker(state: AddFlowState): string | null {
  const input = resolveInput(state);
  if (state.step === 1) {
    if (input.kind === "empty") return "Paste a server URL or a command to continue.";
    if (input.kind === "invalid") return input.reason;
    return null;
  }
  if (state.step === 2) {
    if (state.access === "key" && input.kind === "url" && !state.memberSupplied && !state.headerValue.trim()) {
      return "Enter the key, or mark it as something each member provides.";
    }
    if (state.probe?.oauth?.registration === "manual" && state.access === "oauth" && !state.clientId.trim()) {
      return "This provider needs a registered client. Enter the client ID.";
    }
    return null;
  }
  if (state.step === 3 && !state.name.trim()) return "Give the connector a name.";
  return null;
}
