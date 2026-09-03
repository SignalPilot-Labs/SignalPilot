import { describe, expect, it } from "vitest";
import type { Connector, ToolInfo } from "~/lib/api/mcp-connectors";
import {
  FIXTURE_CONNECTORS,
  GITHUB_TOOLS,
  JIRA_TOOLS,
  SLACK_TOOLS,
} from "~/lib/mcp-connectors-fixture";
import {
  bulkToolSettings,
  connectorSubtitle,
  countToolKinds,
  defaultToolSetting,
  deriveConnectorHealth,
  describeNextChatTools,
  describeToolCount,
  filterTools,
  filterToolsByKind,
  groupTools,
  parseServerInput,
  previewSlug,
  slugify,
  sortConnectors,
  sortToolsByKind,
  splitCommand,
  suggestName,
  toolKind,
} from "~/lib/mcp-connectors-state";

const byId = (id: string): Connector => {
  const found = FIXTURE_CONNECTORS.find((c) => c.id === id);
  if (!found) throw new Error(id);
  return JSON.parse(JSON.stringify(found)) as Connector;
};

describe("deriveConnectorHealth", () => {
  it("reads Connected for a healthy signed-in org connector", () => {
    expect(deriveConnectorHealth(byId("con_jira"))).toMatchObject({ label: "Connected", tone: "ok", action: null });
  });
  it("puts the org kill switch above everything else", () => {
    const c = { ...byId("con_jira"), enabled: false, status: "needs_sign_in" as const };
    expect(deriveConnectorHealth(c)).toMatchObject({ label: "Off", detail: "Turned off by your organization", action: null });
  });
  it("shows the member's own switch as Off with a way back on", () => {
    const c = byId("con_jira");
    c.my_state!.enabled = false;
    expect(deriveConnectorHealth(c)).toMatchObject({ label: "Off", detail: "Turned off by you", action: "turn_on" });
  });
  it("asks for sign-in when the member has no token on an OAuth connector", () => {
    const c = byId("con_jira");
    c.my_state!.signed_in = false;
    expect(deriveConnectorHealth(c)).toMatchObject({ label: "Needs sign-in", action: "sign_in" });
  });
  it("asks for the member's key on a member-supplied secret", () => {
    const c = byId("con_github");
    c.my_state!.has_key = false;
    expect(deriveConnectorHealth(c)).toMatchObject({ label: "Needs your key", action: "add_key" });
  });
  it("surfaces unreachable with the cause and a retry", () => {
    expect(deriveConnectorHealth(byId("con_linear"))).toMatchObject({
      label: "Unreachable",
      tone: "error",
      detail: "We couldn't reach this address",
      action: "retry",
    });
  });
  it("flags tools changed for review", () => {
    expect(deriveConnectorHealth(byId("con_slack"))).toMatchObject({ label: "Tools changed", action: "review" });
  });
  it("says Starting… for a pending sandbox connector", () => {
    const c = { ...byId("con_github"), status: "pending" as const };
    expect(deriveConnectorHealth(c).label).toBe("Starting…");
  });
});

describe("row copy", () => {
  it("describes tool counts once", () => {
    expect(describeToolCount(0, 0)).toBe("No tools yet");
    expect(describeToolCount(1, 1)).toBe("1 tool");
    expect(describeToolCount(12, 12)).toBe("12 tools");
    expect(describeToolCount(12, 9)).toBe("12 tools · 9 on");
  });
  it("uses the host for remote and the command for sandbox connectors", () => {
    expect(connectorSubtitle(byId("con_jira"))).toBe("mcp.atlassian.com");
    expect(connectorSubtitle(byId("con_github"))).toBe("npx -y @modelcontextprotocol/server-github");
  });
  it("summarizes what the next chat receives", () => {
    // Jira 5 on, Snowflake 4, Slack is tools_changed (not active), GitHub 8, Linear unreachable.
    expect(describeNextChatTools(FIXTURE_CONNECTORS)).toBe("3 connectors · 17 tools go to your next chat");
    expect(describeNextChatTools([])).toBe("Nothing goes to your next chat yet.");
    const one = { ...byId("con_snowflake_docs"), enabled_tool_count: 1 };
    expect(describeNextChatTools([one])).toBe("1 connector · 1 tool goes to your next chat");
  });
  it("sorts organization first, then by name", () => {
    expect(sortConnectors(FIXTURE_CONNECTORS).map((c) => c.name)).toEqual([
      "Jira",
      "Slack",
      "Snowflake docs",
      "GitHub",
      "Linear",
    ]);
  });
});

describe("tool defaults and grouping (R3)", () => {
  const read: ToolInfo["annotations"] = { read_only_hint: true };
  const write: ToolInfo["annotations"] = {};
  const destructive: ToolInfo["annotations"] = { destructive_hint: true };
  it("seeds read-only on/auto and everything else off", () => {
    expect(defaultToolSetting(read)).toEqual({ enabled: true, policy: "auto" });
    expect(defaultToolSetting(write)).toEqual({ enabled: false, policy: "off" });
    expect(defaultToolSetting(destructive)).toEqual({ enabled: false, policy: "off" });
  });
  it("keeps newly discovered tools off even when read-only", () => {
    expect(defaultToolSetting(read, true)).toEqual({ enabled: false, policy: "off" });
  });
  it("labels the kind from provider annotations", () => {
    expect(toolKind(read)).toBe("read");
    expect(toolKind(write)).toBe("write");
    expect(toolKind(destructive)).toBe("destructive");
  });
  it("groups into on/off and honors the member's own off list", () => {
    const groups = groupTools(SLACK_TOOLS, ["search_messages"]);
    expect(groups.on.map((t) => t.name)).toEqual(["get_channel_history", "get_user_profile", "list_channels"]);
    expect(groups.off.map((t) => t.name)).toContain("search_messages");
    expect(groups.fresh.map((t) => t.name)).toEqual(["delete_message", "schedule_message", "upload_file"]);
    // New tools lead the Off list so the review banner lines up with them.
    expect(groups.off.slice(0, 3).every((t) => t.is_new)).toBe(true);
  });
  it("orders by kind: read-only first in On, writes and destructive first in Off", () => {
    const groups = groupTools(GITHUB_TOOLS);
    // On: reads before the three enabled writes, then by name.
    expect(groups.on.map((t) => toolKind(t.annotations))).toEqual([
      "read", "read", "read", "read", "read", "write", "write", "write",
    ]);
    expect(groups.on[0].name).toBe("get_file_contents");
    // Off: destructive first, then writes.
    expect(groups.off.map((t) => t.name)).toEqual([
      "delete_branch", "delete_repository", "merge_pull_request", "push_files",
    ]);
    // New tools still lead a group, whatever their kind.
    const fresh = sortToolsByKind(SLACK_TOOLS, "safe_first");
    expect(fresh.slice(0, 3).every((t) => t.is_new)).toBe(true);
  });
  it("counts and filters by kind", () => {
    expect(countToolKinds(GITHUB_TOOLS)).toEqual({ all: 12, read: 5, write: 5, destructive: 2 });
    expect(filterToolsByKind(GITHUB_TOOLS, "destructive").map((t) => t.name)).toEqual(["delete_branch", "delete_repository"]);
    expect(filterToolsByKind(GITHUB_TOOLS, "all")).toHaveLength(12);
  });
  it("builds bulk settings", () => {
    const on = bulkToolSettings(GITHUB_TOOLS, "on_read_only");
    expect(on.get_file_contents).toEqual({ enabled: true, policy: "auto" });
    expect(on.create_pull_request).toEqual({ enabled: false, policy: "off" });
    const off = bulkToolSettings(GITHUB_TOOLS, "off_all");
    expect(Object.values(off).every((v) => v.enabled === false)).toBe(true);
  });
  it("filters by name, title, and description", () => {
    expect(filterTools(JIRA_TOOLS, "burndown").map((t) => t.name)).toEqual(["get_sprint"]);
    expect(filterTools(JIRA_TOOLS, "JQL").map((t) => t.name)).toEqual(["search_issues"]);
    expect(filterTools(JIRA_TOOLS, "")).toHaveLength(JIRA_TOOLS.length);
  });
});

describe("slug rule (R9)", () => {
  it("kebab/snakes the display name within [a-z0-9_]{2,40}", () => {
    expect(slugify("Snowflake docs")).toBe("snowflake_docs");
    expect(slugify("  Jira -- Cloud (EU) ")).toBe("jira_cloud_eu");
    expect(slugify("Ünïcödé Ñame")).toBe("unicode_name");
    expect(slugify("x".repeat(60))).toHaveLength(40);
    expect(slugify("!!")).toBe("");
    expect(slugify("A")).toBe("a_server");
  });
  it("appends _mine to a personal slug that collides with an org slug", () => {
    const existing = FIXTURE_CONNECTORS.map(({ slug, scope }) => ({ slug, scope }));
    expect(previewSlug("Jira", "personal", existing)).toEqual({ slug: "jira_mine", suffixed: true, taken: false });
    expect(previewSlug("Jira", "org", existing)).toEqual({ slug: "jira", suffixed: false, taken: true });
    expect(previewSlug("GitHub", "personal", existing)).toEqual({ slug: "github", suffixed: false, taken: true });
    expect(previewSlug("Notion", "personal", existing)).toEqual({ slug: "notion", suffixed: false, taken: false });
    expect(previewSlug("", "personal", existing)).toBeNull();
  });
});

describe("parseServerInput", () => {
  it("detects addresses, with or without a scheme", () => {
    expect(parseServerInput("https://mcp.linear.app/mcp")).toEqual({ kind: "url", url: "https://mcp.linear.app/mcp" });
    expect(parseServerInput("mcp.linear.app/mcp")).toEqual({ kind: "url", url: "https://mcp.linear.app/mcp" });
  });
  it("detects commands and splits shell-style", () => {
    expect(parseServerInput("npx -y @modelcontextprotocol/server-github")).toEqual({
      kind: "command",
      command: "npx",
      args: ["-y", "@modelcontextprotocol/server-github"],
    });
    expect(splitCommand(`uvx server --name "My Server" 'a b'`)).toEqual(["uvx", "server", "--name", "My Server", "a b"]);
  });
  it("refuses docker with a specific reason", () => {
    const result = parseServerInput("docker run -i mcp/github");
    expect(result.kind).toBe("invalid");
    expect(result.kind === "invalid" && result.reason).toMatch(/Docker/);
  });
  it("treats a broken address as invalid, not as a command", () => {
    expect(parseServerInput("https://").kind).toBe("invalid");
    expect(parseServerInput("   ").kind).toBe("empty");
  });
});

describe("suggestName", () => {
  it("prefers the server's own name, title-cased", () => {
    expect(suggestName({ kind: "url", url: "https://x.example/mcp" }, "vendor-docs")).toBe("Vendor Docs");
    expect(suggestName({ kind: "command", command: "npx", args: [] }, "github-mcp-server")).toBe("GitHub");
    expect(suggestName({ kind: "url", url: "https://x.example/mcp" }, "Atlassian Rovo MCP")).toBe("Atlassian Rovo");
  });
  it("falls back to the host's core label", () => {
    expect(suggestName({ kind: "url", url: "https://mcp.linear.app/mcp" })).toBe("Linear");
    expect(suggestName({ kind: "url", url: "https://docs-mcp.snowflake.example/mcp" })).toBe("Snowflake");
  });
  it("names a sandbox command from its package", () => {
    expect(suggestName({ kind: "command", command: "npx", args: ["-y", "@modelcontextprotocol/server-github"] })).toBe("GitHub");
  });
});
