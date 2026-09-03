// Fixture connectors for running the Connectors UI without a gateway:
// /settings/connectors?fixture=1 and the /chats/test harness. Shapes follow
// the §2 contract exactly. The in-memory client that mutates these lives in
// lib/mcp-connectors-fixture-client.ts.

import type {
  Connector,
  ConnectorDetail,
  OrgPolicy,
  ToolCall,
  ToolInfo,
} from "~/lib/api/mcp-connectors";
import { brandIconDataUri } from "~/lib/connector-brand-icons";

export const FIXTURE_ORG_ID = "org_fixture";
export const FIXTURE_ORG_NAME = "Acme Analytics";
export const FIXTURE_ME = "user_eli";
/** Readable labels for the fixture members (what the gateway resolves from Clerk). */
export const FIXTURE_USER_LABELS: Record<string, string> = {
  user_eli: "eli@acme-analytics.com",
  user_maya: "maya@acme-analytics.com",
  user_priya: "priya@acme-analytics.com",
};
const T0 = "2026-08-30T09:12:00Z";

function tool(
  name: string,
  description: string,
  kind: "read" | "write" | "destructive",
  extra: Partial<ToolInfo> = {},
): ToolInfo {
  const read = kind === "read";
  return {
    name,
    title: null,
    description,
    annotations:
      kind === "destructive"
        ? { destructive_hint: true, read_only_hint: false }
        : { read_only_hint: read },
    enabled: read,
    policy: read ? "auto" : "off",
    discovered_at: T0,
    is_new: false,
    ...extra,
  };
}

const base = (
  overrides: Partial<Connector> &
    Pick<Connector, "id" | "scope" | "name" | "slug" | "transport" | "auth" | "status">,
): Connector => ({
  org_id: FIXTURE_ORG_ID,
  owner_user_id: overrides.scope === "personal" ? FIXTURE_ME : null,
  url: null,
  command: null,
  args: [],
  env_keys: [],
  header_keys: [],
  status_detail: null,
  protocol_version: "2025-06-18",
  server_name: null,
  enabled: true,
  tool_count: 0,
  enabled_tool_count: 0,
  created_by: "user_maya",
  created_at: T0,
  updated_at: T0,
  last_used_at: null,
  my_state: { enabled: true, disabled_tools: [], signed_in: false, has_key: false, signed_in_at: null },
  icon_url: null,
  signed_in_count: null,
  tools_added: null,
  tools_removed: null,
  ...overrides,
});

export const JIRA_TOOLS: ToolInfo[] = [
  tool("search_issues", "Search issues with JQL. Returns key, summary, status, assignee.", "read"),
  tool("get_issue", "Fetch one issue by key including comments and attachments metadata.", "read"),
  tool("list_projects", "List the projects the signed-in user can see.", "read"),
  tool("list_boards", "List agile boards and their active sprints.", "read"),
  tool("get_sprint", "Get a sprint with its issues and burndown totals.", "read"),
  tool("create_issue", "Create an issue in a project. Requires a summary and issue type.", "write"),
  tool("add_comment", "Add a comment to an issue as the signed-in user.", "write"),
  tool("transition_issue", "Move an issue to another workflow status.", "write"),
  tool("assign_issue", "Assign an issue to a user.", "write"),
  tool("delete_issue", "Permanently delete an issue and its comments.", "destructive"),
];

export const SNOWFLAKE_DOCS_TOOLS: ToolInfo[] = [
  tool("search_docs", "Full-text search over Snowflake documentation.", "read"),
  tool("get_page", "Return one documentation page as plain text.", "read"),
  tool("list_sql_functions", "List SQL functions by category with signatures.", "read"),
  tool("explain_error_code", "Look up a Snowflake error code and its remedies.", "read"),
];

export const GITHUB_TOOLS: ToolInfo[] = [
  tool("get_file_contents", "Read a file or directory from a repository.", "read"),
  tool("search_code", "Search code across repositories the token can access.", "read"),
  tool("list_issues", "List issues in a repository with filters.", "read"),
  tool("get_pull_request", "Get a pull request with its reviews and checks.", "read"),
  tool("list_commits", "List commits on a branch.", "read"),
  tool("create_branch", "Create a branch from a ref.", "write", { enabled: true, policy: "auto" }),
  tool("create_or_update_file", "Write a single file and commit it.", "write", { enabled: true, policy: "auto" }),
  tool("create_pull_request", "Open a pull request between two branches.", "write", { enabled: true, policy: "auto" }),
  tool("push_files", "Push multiple files in one commit.", "write"),
  tool("merge_pull_request", "Merge a pull request.", "write"),
  tool("delete_branch", "Delete a branch. Cannot be undone.", "destructive"),
  tool("delete_repository", "Delete a repository. Cannot be undone.", "destructive"),
];

export const LINEAR_TOOLS: ToolInfo[] = [
  tool("list_issues", "List issues assigned to the signed-in user.", "read"),
  tool("get_issue", "Get one issue with comments.", "read"),
  tool("create_issue", "Create an issue in a team.", "write"),
];

const NEW_AT = "2026-08-31T22:41:00Z";
export const SLACK_TOOLS: ToolInfo[] = [
  tool("search_messages", "Search messages the signed-in user can read.", "read"),
  tool("list_channels", "List public channels and their topics.", "read"),
  tool("get_channel_history", "Read recent messages from a channel.", "read"),
  tool("get_user_profile", "Get a user's display name, title, and timezone.", "read"),
  tool("send_message", "Post a message to a channel or DM as the signed-in user.", "write"),
  tool("add_reaction", "Add an emoji reaction to a message.", "write"),
  tool("schedule_message", "Post a message at a later time.", "write", { is_new: true, discovered_at: NEW_AT }),
  tool("upload_file", "Upload a file to a channel.", "write", { is_new: true, discovered_at: NEW_AT }),
  tool("delete_message", "Delete a message the signed-in user posted.", "destructive", { is_new: true, discovered_at: NEW_AT }),
];

const withCounts = (connector: Connector, tools: ToolInfo[]): Connector => ({
  ...connector,
  tool_count: tools.length,
  enabled_tool_count: tools.filter((t) => t.enabled).length,
});

export const FIXTURE_CONNECTORS: Connector[] = [
  withCounts(
    base({
      id: "con_jira",
      scope: "org",
      name: "Jira",
      slug: "jira",
      transport: "http",
      auth: "oauth",
      status: "connected",
      url: "https://mcp.atlassian.com/v1/mcp",
      server_name: "Atlassian Rovo MCP",
      last_used_at: "2026-09-01T08:02:00Z",
      icon_url: brandIconDataUri("atlassian"),
      signed_in_count: 3,
      my_state: {
        enabled: true,
        disabled_tools: [],
        signed_in: true,
        has_key: false,
        signed_in_at: "2026-08-30T10:04:00Z",
        account_label: "eli@acme-analytics.com",
      },
    }),
    JIRA_TOOLS,
  ),
  withCounts(
    base({
      id: "con_snowflake_docs",
      scope: "org",
      name: "Snowflake docs",
      slug: "snowflake_docs",
      transport: "http",
      auth: "key",
      status: "connected",
      url: "https://docs-mcp.snowflake.example/mcp",
      server_name: "snowflake-docs",
      header_keys: [{ name: "X-API-Key", has_value: true }],
      last_used_at: "2026-08-31T16:40:00Z",
      icon_url: brandIconDataUri("snowflake"),
      signed_in_count: 0,
    }),
    SNOWFLAKE_DOCS_TOOLS,
  ),
  withCounts(
    base({
      id: "con_slack",
      scope: "org",
      name: "Slack",
      slug: "slack",
      transport: "http",
      auth: "oauth",
      status: "tools_changed",
      status_detail: "3 new tools since last check",
      url: "https://mcp.slack.com/mcp",
      server_name: "Slack MCP",
      last_used_at: "2026-08-31T14:12:00Z",
      icon_url: brandIconDataUri("slack"),
      signed_in_count: 2,
      tools_added: 3,
      tools_removed: 1,
      my_state: {
        enabled: true,
        disabled_tools: ["add_reaction"],
        signed_in: true,
        has_key: false,
        signed_in_at: "2026-08-30T10:06:00Z",
        account_label: "@eli",
      },
    }),
    SLACK_TOOLS,
  ),
  withCounts(
    base({
      id: "con_github",
      scope: "personal",
      name: "GitHub",
      slug: "github",
      transport: "stdio",
      auth: "none",
      status: "connected",
      command: "npx",
      args: ["-y", "@modelcontextprotocol/server-github"],
      env_keys: [
        { name: "GITHUB_PERSONAL_ACCESS_TOKEN", secret: true, has_value: true, member_supplied: true },
        { name: "GITHUB_API_URL", secret: false, has_value: true, member_supplied: false },
      ],
      protocol_version: "2025-03-26",
      server_name: "github-mcp-server",
      created_by: FIXTURE_ME,
      created_at: "2026-08-28T15:20:00Z",
      last_used_at: "2026-09-01T07:55:00Z",
      // Sandbox connectors have no icon endpoint; the fixture still shows the
      // mark the curated set would pick from the package name.
      icon_url: brandIconDataUri("github"),
      my_state: { enabled: true, disabled_tools: [], signed_in: false, has_key: true, signed_in_at: null },
    }),
    GITHUB_TOOLS,
  ),
  withCounts(
    base({
      id: "con_linear",
      scope: "personal",
      name: "Linear",
      slug: "linear",
      transport: "sse",
      auth: "oauth",
      status: "unreachable",
      status_detail: "We couldn't reach this address",
      url: "https://mcp.linear.app/sse",
      protocol_version: "2024-11-05",
      created_by: FIXTURE_ME,
      created_at: "2026-08-29T11:00:00Z",
      icon_url: brandIconDataUri("linear"),
      my_state: {
        enabled: true,
        disabled_tools: [],
        signed_in: true,
        has_key: false,
        signed_in_at: "2026-08-29T11:02:00Z",
        account_label: "eli@acme-analytics.com",
      },
    }),
    LINEAR_TOOLS,
  ),
];

export const FIXTURE_TOOLS: Record<string, ToolInfo[]> = {
  con_jira: JIRA_TOOLS,
  con_snowflake_docs: SNOWFLAKE_DOCS_TOOLS,
  con_slack: SLACK_TOOLS,
  con_github: GITHUB_TOOLS,
  con_linear: LINEAR_TOOLS,
};

export const FIXTURE_POLICY: OrgPolicy = {
  allow_personal: true,
  allowed_hosts: [],
  updated_at: T0,
};

const call = (
  id: string,
  connector_id: string,
  connector_name: string,
  user_id: string,
  toolName: string,
  minutesAgo: number,
  outcome: ToolCall["outcome"] = "ok",
  duration_ms = 420,
  error: string | null = null,
): ToolCall => ({
  id,
  connector_id,
  connector_name,
  user_id,
  user_label: FIXTURE_USER_LABELS[user_id] ?? null,
  run_id: `run_${id}`,
  conversation_id: `conv_${id.slice(-2)}`,
  tool: toolName,
  outcome,
  duration_ms,
  error,
  called_at: new Date(Date.UTC(2026, 8, 1, 9, 30) - minutesAgo * 60_000).toISOString(),
});

export const FIXTURE_CALLS: ToolCall[] = [
  call("tc_01", "con_jira", "Jira", FIXTURE_ME, "search_issues", 3),
  call("tc_02", "con_jira", "Jira", FIXTURE_ME, "get_issue", 3, "ok", 210),
  call("tc_03", "con_jira", "Jira", "user_maya", "list_boards", 42, "ok", 380),
  call("tc_04", "con_jira", "Jira", "user_priya", "delete_issue", 55, "denied", 4, "Tool is off for this connector"),
  call("tc_05", "con_jira", "Jira", FIXTURE_ME, "search_issues", 130, "error", 1_840, "Upstream returned 502"),
  call("tc_06", "con_snowflake_docs", "Snowflake docs", "user_maya", "search_docs", 860),
  call("tc_07", "con_slack", "Slack", FIXTURE_ME, "search_messages", 1_150),
  call("tc_08", "con_slack", "Slack", FIXTURE_ME, "get_channel_history", 1_149, "ok", 640),
];

export function fixtureDetail(connector: Connector): ConnectorDetail {
  return { ...connector, tools: FIXTURE_TOOLS[connector.id] ?? [] };
}

/** Probe outcomes for the add flow, keyed by what the user pastes. */
export function fixtureProbe(input: { url?: string; command?: string; args?: string[] }) {
  if (input.command) {
    if (/github/.test((input.args ?? []).join(" "))) {
      return {
        transport: "stdio" as const,
        auth: "none" as const,
        server_name: "github-mcp-server",
        protocol_version: "2025-03-26",
        tools: GITHUB_TOOLS.slice(0, 8).map((t) => ({ ...t, enabled: Boolean(t.annotations.read_only_hint) })),
      };
    }
    if (input.command === "npx" || input.command === "uvx") {
      return {
        transport: "stdio" as const,
        auth: "none" as const,
        server_name: "filesystem-mcp",
        protocol_version: "2025-03-26",
        tools: [
          tool("read_file", "Read the contents of a file in the sandbox.", "read"),
          tool("list_directory", "List files in a directory.", "read"),
          tool("write_file", "Create or overwrite a file.", "write"),
          tool("move_file", "Move or rename a file.", "write"),
        ],
      };
    }
    return { transport: "stdio" as const, auth: "unknown" as const, error: "The command didn't start" };
  }
  const url = input.url ?? "";
  if (/unreachable|nowhere/.test(url)) {
    return { transport: "http" as const, auth: "unknown" as const, error: "We couldn't reach this address" };
  }
  if (/key|docs/.test(url)) {
    return {
      transport: "http" as const,
      auth: "key" as const,
      server_name: "vendor-docs",
      protocol_version: "2025-06-18",
      tools: [
        tool("search", "Search the documentation.", "read"),
        tool("get_page", "Read one page.", "read"),
      ],
    };
  }
  return {
    transport: "http" as const,
    auth: "oauth" as const,
    server_name: "Vendor Docs",
    protocol_version: "2025-06-18",
    oauth: { authorization_server: "https://auth.vendor.example", registration: "dcr" as const },
    tools: [
      tool("search", "Search the vendor's documentation.", "read"),
      tool("get_article", "Read one article as plain text.", "read"),
      tool("list_products", "List products with their doc sections.", "read"),
      tool("open_ticket", "Open a support ticket on the user's behalf.", "write"),
    ],
  };
}
