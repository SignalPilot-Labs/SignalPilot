// The one surface the Connectors UI talks to. The live implementation wraps
// the thin gateway client; the fixture implementation (lib/
// mcp-connectors-fixture-client.ts) keeps the same shape in memory so every
// screen runs without a gateway.

import {
  createMcpConnector,
  deleteMcpConnector,
  deleteMcpConnectorSecret,
  getMcpConnector,
  getMcpConnectorActivity,
  getMcpOrgActivity,
  listMcpConnectors,
  mcpConnectorOAuthStartUrl,
  patchMcpConnector,
  probeMcpConnector,
  refreshMcpConnectorTools,
  signOutMcpConnector,
  updateMcpConnectorMemberState,
  updateMcpConnectorSecrets,
  updateMcpConnectorTools,
  updateMcpOrgPolicy,
  type Connector,
  type ConnectorCreate,
  type ConnectorDetail,
  type ConnectorPatch,
  type ConnectorsListResponse,
  type MemberState,
  type MemberStateUpdate,
  type OrgPolicy,
  type ProbeRequest,
  type ProbeResult,
  type SecretsUpdate,
  type ToolCall,
  type ToolSettingsUpdate,
} from "~/lib/api/mcp-connectors";

export type SignInResult =
  | { outcome: "signed_in"; state: MemberState }
  | { outcome: "cancelled" }
  | { outcome: "blocked"; url: string }
  | { outcome: "error"; message: string };

export type ConnectorsApi = {
  list(): Promise<ConnectorsListResponse>;
  probe(body: ProbeRequest): Promise<ProbeResult>;
  create(body: ConnectorCreate): Promise<Connector>;
  get(id: string): Promise<ConnectorDetail>;
  patch(id: string, body: ConnectorPatch): Promise<Connector>;
  remove(id: string): Promise<void>;
  refreshTools(id: string): Promise<ConnectorDetail>;
  updateTools(id: string, body: ToolSettingsUpdate): Promise<ConnectorDetail>;
  updateMe(id: string, body: MemberStateUpdate): Promise<MemberState>;
  updateSecrets(id: string, body: SecretsUpdate): Promise<Connector>;
  deleteSecret(id: string, name: string): Promise<Connector>;
  /** Runs the provider sign-in (a popup on the live client) to completion. */
  signIn(id: string): Promise<SignInResult>;
  signOut(id: string, everyone?: boolean): Promise<MemberState>;
  activity(id: string): Promise<ToolCall[]>;
  orgActivity(): Promise<ToolCall[]>;
  updatePolicy(body: OrgPolicy): Promise<OrgPolicy>;
};

const SIGN_IN_TIMEOUT_MS = 10 * 60_000;
const POLL_MS = 1_500;

/**
 * Opens the gateway's sign-in redirect in a popup and polls the connector
 * until the member state reports signed in, the popup closes, or ten minutes
 * pass (the gateway's pending-state expiry). The callback page can't post
 * back to us cross-origin, so polling is the honest signal.
 */
async function runSignInPopup(id: string): Promise<SignInResult> {
  const redirectAfter =
    typeof window === "undefined" ? "/settings/connectors" : window.location.pathname;
  const url = mcpConnectorOAuthStartUrl(id, redirectAfter);
  const popup = window.open(
    url,
    "sp-connector-sign-in",
    "popup=yes,width=520,height=680,noopener=no",
  );
  if (!popup) return { outcome: "blocked", url };
  const startedAt = Date.now();
  while (Date.now() - startedAt < SIGN_IN_TIMEOUT_MS) {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    let detail: ConnectorDetail;
    try {
      detail = await getMcpConnector(id);
    } catch (error) {
      return { outcome: "error", message: (error as Error).message };
    }
    if (detail.my_state?.signed_in) {
      try {
        popup.close();
      } catch {
        /* provider page may already be gone */
      }
      return { outcome: "signed_in", state: detail.my_state };
    }
    if (popup.closed) return { outcome: "cancelled" };
  }
  return { outcome: "error", message: "The sign-in window timed out." };
}

export const liveConnectorsApi: ConnectorsApi = {
  list: listMcpConnectors,
  probe: probeMcpConnector,
  create: createMcpConnector,
  get: getMcpConnector,
  patch: patchMcpConnector,
  remove: deleteMcpConnector,
  refreshTools: refreshMcpConnectorTools,
  updateTools: updateMcpConnectorTools,
  updateMe: updateMcpConnectorMemberState,
  updateSecrets: updateMcpConnectorSecrets,
  deleteSecret: deleteMcpConnectorSecret,
  signIn: runSignInPopup,
  signOut: signOutMcpConnector,
  activity: (id) => getMcpConnectorActivity(id).then((r) => r.calls),
  orgActivity: () => getMcpOrgActivity().then((r) => r.calls),
  updatePolicy: updateMcpOrgPolicy,
};
