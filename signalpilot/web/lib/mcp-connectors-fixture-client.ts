// In-memory ConnectorsApi over the fixture data. Every mutation the real
// gateway would perform is mirrored here (member state, tool policy, org
// policy, probe → create, sign-in) so the settings page, add flow, drawer
// and chat panel all work end to end at /settings/connectors?fixture=1.

import type {
  Connector,
  ConnectorCreate,
  ConnectorDetail,
  MemberState,
  OrgPolicy,
  ToolCall,
  ToolInfo,
} from "~/lib/api/mcp-connectors";
import type { ConnectorsApi } from "~/components/connectors/connectors-api";
import { defaultToolSetting, previewSlug } from "~/lib/mcp-connectors-state";
import { brandIconDataUri, brandIconKeyForHost } from "~/lib/connector-brand-icons";
import { hostOf } from "~/lib/mcp-connectors-state";
import {
  FIXTURE_CALLS,
  FIXTURE_CONNECTORS,
  FIXTURE_ME,
  FIXTURE_ORG_ID,
  FIXTURE_ORG_NAME,
  FIXTURE_POLICY,
  FIXTURE_TOOLS,
  fixtureProbe,
} from "~/lib/mcp-connectors-fixture";

export type FixtureClientOptions = {
  isAdmin?: boolean;
  /** Simulated network latency; 0 in tests. */
  latencyMs?: number;
  /** Start empty to exercise the empty states. */
  empty?: boolean;
};

const clone = <T>(value: T): T =>
  value === undefined ? value : (JSON.parse(JSON.stringify(value)) as T);

export function createFixtureConnectorsApi(
  options: FixtureClientOptions = {},
): ConnectorsApi & { reset(): void } {
  const latency = options.latencyMs ?? 180;
  let connectors: Connector[] = [];
  let tools: Record<string, ToolInfo[]> = {};
  let policy: OrgPolicy = clone(FIXTURE_POLICY);
  let calls: ToolCall[] = [];
  let nextId = 1;

  const reset = () => {
    connectors = options.empty ? [] : clone(FIXTURE_CONNECTORS);
    tools = options.empty ? {} : clone(FIXTURE_TOOLS);
    policy = clone(FIXTURE_POLICY);
    calls = options.empty ? [] : clone(FIXTURE_CALLS);
  };
  reset();

  const wait = <T>(value: T): Promise<T> =>
    new Promise((resolve) => setTimeout(() => resolve(clone(value)), latency));
  const fail = (message: string) => Promise.reject(new Error(message));

  const find = (id: string) => {
    const connector = connectors.find((c) => c.id === id);
    if (!connector) throw new Error(`404: connector ${id} not found`);
    return connector;
  };
  const recount = (connector: Connector) => {
    const list = tools[connector.id] ?? [];
    connector.tool_count = list.length;
    connector.enabled_tool_count = list.filter((t) => t.enabled).length;
    connector.updated_at = new Date().toISOString();
  };
  const detail = (connector: Connector): ConnectorDetail => ({
    ...connector,
    tools: tools[connector.id] ?? [],
  });
  const requireAdmin = (connector: Connector) => {
    if (connector.scope === "org" && options.isAdmin === false) {
      throw new Error("403: organization connectors are managed by an admin");
    }
  };

  return {
    reset,
    list: () =>
      wait({ connectors, policy, is_admin: options.isAdmin ?? true, org_name: FIXTURE_ORG_NAME }),
    probe: (body) => {
      const result = fixtureProbe(body);
      return new Promise((resolve) =>
        setTimeout(() => resolve(clone(result)), body.command ? latency * 6 : latency * 3),
      );
    },
    create: (body: ConnectorCreate) => {
      if (body.scope === "org" && options.isAdmin === false) {
        return fail("403: only an admin can add a connector for everyone");
      }
      const preview = previewSlug(body.name, body.scope, connectors);
      if (!preview) return fail("400: name is required");
      if (preview.taken) return fail("409: You already have a connector with this name");
      const probe = fixtureProbe({ url: body.url, command: body.command, args: body.args });
      const id = `con_new_${nextId++}`;
      const now = new Date().toISOString();
      const transport = body.transport ?? probe.transport;
      const auth = body.auth ?? (probe.auth === "unknown" ? "none" : probe.auth);
      const memberSecret = (body.env ?? []).some((e) => e.secret && e.member_supplied && !e.value);
      // Remote connectors get an icon through the gateway's proxy; the
      // fixture mints a data: URI for hosts the curated set knows.
      const iconKey = body.url ? brandIconKeyForHost(hostOf(body.url)) : null;
      const connector: Connector = {
        id,
        org_id: FIXTURE_ORG_ID,
        scope: body.scope,
        owner_user_id: body.scope === "personal" ? FIXTURE_ME : null,
        name: body.name,
        slug: preview.slug,
        transport,
        url: body.url ?? null,
        command: body.command ?? null,
        args: body.args ?? [],
        env_keys: (body.env ?? []).map((e) => ({
          name: e.name,
          secret: e.secret,
          has_value: Boolean(e.value),
          member_supplied: e.member_supplied,
        })),
        header_keys: Object.keys(body.headers ?? {}).map((name) => ({ name, has_value: true })),
        auth,
        status: probe.error ? "unreachable" : auth === "oauth" ? "needs_sign_in" : memberSecret ? "needs_key" : "connected",
        status_detail: probe.error ?? null,
        protocol_version: probe.protocol_version ?? null,
        server_name: probe.server_name ?? null,
        enabled: true,
        tool_count: 0,
        enabled_tool_count: 0,
        created_by: FIXTURE_ME,
        created_at: now,
        updated_at: now,
        last_used_at: null,
        my_state: {
          enabled: true,
          disabled_tools: [],
          signed_in: false,
          has_key: !memberSecret,
          signed_in_at: null,
          account_label: null,
        },
        icon_url: iconKey ? brandIconDataUri(iconKey) : null,
        signed_in_count: body.scope === "org" ? 0 : null,
        tools_added: null,
        tools_removed: null,
      };
      tools[id] = (probe.tools ?? []).map((tool) => ({
        ...tool,
        ...defaultToolSetting(tool.annotations),
        discovered_at: now,
      }));
      recount(connector);
      connectors.push(connector);
      return wait(connector);
    },
    get: async (id) => wait(detail(find(id))),
    patch: async (id, body) => {
      const connector = find(id);
      requireAdmin(connector);
      Object.assign(connector, body, { updated_at: new Date().toISOString() });
      if (body.enabled === false) connector.status = "disabled";
      if (body.enabled === true && connector.status === "disabled") connector.status = "connected";
      return wait(connector);
    },
    remove: async (id) => {
      const connector = find(id);
      requireAdmin(connector);
      connectors = connectors.filter((c) => c.id !== id);
      delete tools[id];
      return wait(undefined);
    },
    refreshTools: async (id) => {
      const connector = find(id);
      for (const tool of tools[id] ?? []) tool.is_new = false;
      if (connector.status === "tools_changed") {
        connector.status = "connected";
        connector.status_detail = null;
        connector.tools_added = null;
        connector.tools_removed = null;
      }
      recount(connector);
      return wait(detail(connector));
    },
    updateTools: async (id, body) => {
      const connector = find(id);
      const me = connector.my_state ?? { enabled: true, disabled_tools: [], signed_in: false, has_key: false, signed_in_at: null };
      const memberOnly = connector.scope === "org" && options.isAdmin === false;
      for (const tool of tools[id] ?? []) {
        const next = body.tools[tool.name];
        if (!next) continue;
        if (memberOnly) {
          // A member may only turn org tools OFF for themselves.
          me.disabled_tools = next.enabled
            ? me.disabled_tools.filter((name) => name !== tool.name)
            : Array.from(new Set([...me.disabled_tools, tool.name]));
          continue;
        }
        tool.enabled = next.enabled;
        tool.policy = next.policy;
        tool.is_new = false;
      }
      connector.my_state = me;
      if (connector.status === "tools_changed" && !(tools[id] ?? []).some((t) => t.is_new)) {
        connector.status = "connected";
        connector.status_detail = null;
        connector.tools_added = null;
        connector.tools_removed = null;
      }
      recount(connector);
      return wait(detail(connector));
    },
    updateMe: async (id, body) => {
      const connector = find(id);
      const me: MemberState = {
        ...(connector.my_state ?? { enabled: true, disabled_tools: [], signed_in: false, has_key: false, signed_in_at: null }),
        enabled: body.enabled,
        disabled_tools: body.disabled_tools ?? connector.my_state?.disabled_tools ?? [],
      };
      connector.my_state = me;
      return wait(me);
    },
    updateSecrets: async (id, body) => {
      const connector = find(id);
      for (const name of Object.keys(body.headers ?? {})) {
        const key = connector.header_keys.find((k) => k.name === name);
        if (key) key.has_value = true;
        else connector.header_keys.push({ name, has_value: true });
      }
      for (const name of Object.keys(body.env ?? {})) {
        const key = connector.env_keys.find((k) => k.name === name);
        if (key) key.has_value = true;
        if (key?.member_supplied && connector.my_state) connector.my_state.has_key = true;
      }
      if (connector.status === "needs_key") connector.status = "connected";
      connector.updated_at = new Date().toISOString();
      return wait(connector);
    },
    deleteSecret: async (id, name) => {
      const connector = find(id);
      const header = connector.header_keys.find((k) => k.name === name);
      if (header) header.has_value = false;
      const env = connector.env_keys.find((k) => k.name === name);
      if (env) {
        env.has_value = false;
        if (env.member_supplied && connector.my_state) connector.my_state.has_key = false;
      }
      return wait(connector);
    },
    signIn: async (id) => {
      const connector = find(id);
      await new Promise((resolve) => setTimeout(resolve, latency * 4));
      const me: MemberState = {
        ...(connector.my_state ?? { enabled: true, disabled_tools: [], has_key: false }),
        signed_in: true,
        signed_in_at: new Date().toISOString(),
        account_label: "eli@acme-analytics.com",
      } as MemberState;
      connector.my_state = me;
      if (connector.status === "needs_sign_in") connector.status = "connected";
      if (connector.scope === "org" && typeof connector.signed_in_count === "number") {
        connector.signed_in_count += 1;
      }
      return { outcome: "signed_in", state: clone(me) };
    },
    signOut: async (id, everyone) => {
      const connector = find(id);
      if (everyone) requireAdmin(connector);
      const me: MemberState = {
        ...(connector.my_state ?? { enabled: true, disabled_tools: [], has_key: false }),
        signed_in: false,
        signed_in_at: null,
        account_label: null,
      } as MemberState;
      connector.my_state = me;
      if (connector.scope === "personal") connector.status = "needs_sign_in";
      if (connector.scope === "org" && typeof connector.signed_in_count === "number") {
        connector.signed_in_count = everyone ? 0 : Math.max(0, connector.signed_in_count - 1);
      }
      return wait(me);
    },
    activity: async (id) => wait(calls.filter((c) => c.connector_id === id)),
    orgActivity: () => wait(calls),
    updatePolicy: async (body) => {
      if (options.isAdmin === false) return fail("403: only an admin can change the policy");
      policy = { ...body, updated_at: new Date().toISOString() };
      return wait(policy);
    },
  };
}
