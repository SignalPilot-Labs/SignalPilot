// Connectors: external MCP servers the chat agent can use.
// Thin wrappers over the gateway's /api/mcp routes. The shapes mirror the
// spec's §2 contract exactly (snake_case, same enums) so the fixture layer
// and the live gateway are interchangeable.

import { GATEWAY_URL, request } from "./client";

export type ConnectorScope = "org" | "personal";
export type ConnectorTransport = "http" | "sse" | "stdio";
export type ConnectorAuth = "none" | "oauth" | "key";
export type ConnectorStatus =
  | "connected"
  | "needs_sign_in"
  | "needs_key"
  | "unreachable"
  | "tools_changed"
  | "disabled"
  | "pending";
export type ToolPolicy = "auto" | "ask" | "off";
export type ToolCallOutcome = "ok" | "error" | "denied";

export type ConnectorEnvKey = {
  name: string;
  secret: boolean;
  has_value: boolean;
  member_supplied: boolean;
};

export type ConnectorHeaderKey = { name: string; has_value: boolean };

export type MemberState = {
  enabled: boolean;
  disabled_tools: string[];
  signed_in: boolean;
  has_key: boolean;
  signed_in_at: string | null;
  /** "Signed in as …": the provider account label, when the gateway knows it. */
  account_label?: string | null;
};

export type ToolAnnotations = {
  read_only_hint?: boolean;
  destructive_hint?: boolean;
  idempotent_hint?: boolean;
  open_world_hint?: boolean;
};

export type ToolInfo = {
  name: string;
  title: string | null;
  /** Plain text from the provider. Untrusted: never render as markup. */
  description: string;
  annotations: ToolAnnotations;
  enabled: boolean;
  policy: ToolPolicy;
  discovered_at: string;
  is_new: boolean;
};

export type Connector = {
  id: string;
  org_id: string;
  scope: ConnectorScope;
  owner_user_id: string | null;
  name: string;
  slug: string;
  transport: ConnectorTransport;
  url: string | null;
  command: string | null;
  args: string[];
  env_keys: ConnectorEnvKey[];
  header_keys: ConnectorHeaderKey[];
  auth: ConnectorAuth;
  status: ConnectorStatus;
  status_detail: string | null;
  protocol_version: string | null;
  server_name: string | null;
  enabled: boolean;
  tool_count: number;
  enabled_tool_count: number;
  created_by: string;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
  my_state: MemberState | null;
  // ── Additive fields (null when the gateway has nothing to say) ──
  /** Gateway-relative icon path (`/api/mcp/connectors/{id}/icon`), a data: URI in fixtures, null for sandbox connectors. */
  icon_url?: string | null;
  /** Org connectors, admins only: how many members currently hold a sign-in. */
  signed_in_count?: number | null;
  /** Tools added / removed since the last review (status `tools_changed`). */
  tools_added?: number | null;
  tools_removed?: number | null;
};

export type ConnectorDetail = Connector & { tools: ToolInfo[] };

export type ToolCall = {
  id: string;
  connector_id: string;
  connector_name: string;
  user_id: string;
  /** Email or display name resolved server-side; null when unknown. */
  user_label?: string | null;
  run_id: string | null;
  conversation_id: string | null;
  tool: string;
  outcome: ToolCallOutcome;
  duration_ms: number;
  error: string | null;
  called_at: string;
};

export type OrgPolicy = {
  allow_personal: boolean;
  allowed_hosts: string[];
  updated_at: string;
};

export type ConnectorsListResponse = {
  connectors: Connector[];
  policy: OrgPolicy;
  is_admin: boolean;
  /** Display name of the caller's organization ("Everyone in Acme"). */
  org_name?: string | null;
};

export type ProbeRequest = { url?: string; command?: string; args?: string[] };

export type ProbeResult = {
  transport: ConnectorTransport;
  auth: "none" | "oauth" | "key" | "unknown";
  server_name?: string;
  protocol_version?: string;
  tools?: ToolInfo[];
  oauth?: {
    authorization_server: string;
    registration: "cimd" | "dcr" | "manual";
  };
  error?: string;
};

export type ConnectorCreateEnv = {
  name: string;
  value?: string;
  secret: boolean;
  member_supplied: boolean;
};

export type ConnectorCreate = {
  scope: ConnectorScope;
  name: string;
  transport?: ConnectorTransport;
  url?: string;
  command?: string;
  args?: string[];
  env?: ConnectorCreateEnv[];
  headers?: Record<string, string>;
  auth?: ConnectorAuth;
  oauth_client?: { client_id: string; client_secret?: string };
};

export type ConnectorPatch = {
  name?: string;
  enabled?: boolean;
  url?: string;
  command?: string;
  args?: string[];
  auth?: ConnectorAuth;
};

export type ToolSettingsUpdate = {
  tools: Record<string, { enabled: boolean; policy: "auto" | "off" }>;
};

export type MemberStateUpdate = { enabled: boolean; disabled_tools?: string[] };

export type SecretsUpdate = {
  headers?: Record<string, string>;
  env?: Record<string, string>;
};

const BASE = "/api/mcp";
const id = (value: string) => encodeURIComponent(value);

export const listMcpConnectors = () =>
  request<ConnectorsListResponse>(`${BASE}/connectors`);

export const probeMcpConnector = (body: ProbeRequest) =>
  request<ProbeResult>(`${BASE}/connectors/probe`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const createMcpConnector = (body: ConnectorCreate) =>
  request<Connector>(`${BASE}/connectors`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getMcpConnector = (connectorId: string) =>
  request<ConnectorDetail>(`${BASE}/connectors/${id(connectorId)}`);

export const patchMcpConnector = (connectorId: string, body: ConnectorPatch) =>
  request<Connector>(`${BASE}/connectors/${id(connectorId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteMcpConnector = (connectorId: string) =>
  request<void>(`${BASE}/connectors/${id(connectorId)}`, { method: "DELETE" });

export const refreshMcpConnectorTools = (connectorId: string) =>
  request<ConnectorDetail>(
    `${BASE}/connectors/${id(connectorId)}/refresh-tools`,
    { method: "POST" },
  );

export const updateMcpConnectorTools = (
  connectorId: string,
  body: ToolSettingsUpdate,
) =>
  request<ConnectorDetail>(`${BASE}/connectors/${id(connectorId)}/tools`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const updateMcpConnectorMemberState = (
  connectorId: string,
  body: MemberStateUpdate,
) =>
  request<MemberState>(`${BASE}/connectors/${id(connectorId)}/me`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const updateMcpConnectorSecrets = (
  connectorId: string,
  body: SecretsUpdate,
) =>
  request<Connector>(`${BASE}/connectors/${id(connectorId)}/secrets`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteMcpConnectorSecret = (connectorId: string, name: string) =>
  request<Connector>(
    `${BASE}/connectors/${id(connectorId)}/secrets/${id(name)}`,
    { method: "DELETE" },
  );

/** Browser navigation target for the sign-in flow (a 302 to the provider). */
export const mcpConnectorOAuthStartUrl = (
  connectorId: string,
  redirectAfter: string,
) =>
  `${GATEWAY_URL}${BASE}/connectors/${id(connectorId)}/oauth/start?redirect_after=${encodeURIComponent(redirectAfter)}`;

export const signOutMcpConnector = (connectorId: string, everyone = false) =>
  request<MemberState>(
    `${BASE}/connectors/${id(connectorId)}/oauth/sign-out${everyone ? "?everyone=1" : ""}`,
    { method: "POST" },
  );

export const getMcpConnectorActivity = (connectorId: string, limit = 50) =>
  request<{ calls: ToolCall[] }>(
    `${BASE}/connectors/${id(connectorId)}/activity?limit=${limit}`,
  );

export const getMcpOrgActivity = (limit = 200) =>
  request<{ calls: ToolCall[] }>(`${BASE}/activity?limit=${limit}`);

export const getMcpOrgPolicy = () => request<OrgPolicy>(`${BASE}/policy`);

export const updateMcpOrgPolicy = (body: OrgPolicy) =>
  request<OrgPolicy>(`${BASE}/policy`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
