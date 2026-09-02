import { describe, expect, it } from "vitest";
import { brandIconDataUri, brandIconKeyForHost, brandIconSvg } from "~/lib/connector-brand-icons";
import { FIXTURE_CONNECTORS, FIXTURE_ME } from "~/lib/mcp-connectors-fixture";
import { createFixtureConnectorsApi } from "~/lib/mcp-connectors-fixture-client";
import { connectorDeepLink } from "~/components/chat/chat-settings-panel";
import { describeSignedInMembers } from "./connectors-page";
import { describeCaller } from "./drawer-activity-tab";
import { describeToolsChanged } from "./drawer-tools-tab";
import { describePolicy } from "./org-policy-card";

describe("curated brand icons", () => {
  it("keys well-known hosts and sandbox package names", () => {
    expect(brandIconKeyForHost("mcp.atlassian.com")).toBe("atlassian");
    expect(brandIconKeyForHost("acme.atlassian.net")).toBe("atlassian");
    expect(brandIconKeyForHost("mcp.slack.com")).toBe("slack");
    expect(brandIconKeyForHost("mcp.linear.app")).toBe("linear");
    expect(brandIconKeyForHost("mcp.notion.so")).toBe("notion");
    expect(brandIconKeyForHost("api.github.com")).toBe("github");
    expect(brandIconKeyForHost("npx -y @modelcontextprotocol/server-github")).toBe("github");
    expect(brandIconKeyForHost("snowflake.com")).toBe("snowflake");
    expect(brandIconKeyForHost("docs-mcp.snowflake.example")).toBeNull();
    expect(brandIconKeyForHost("mcp.vendor.example")).toBeNull();
    expect(brandIconKeyForHost(null)).toBeNull();
  });
  it("mints self-contained data: URIs the CSP allows", () => {
    const uri = brandIconDataUri("slack");
    expect(uri?.startsWith("data:image/svg+xml;charset=utf-8,")).toBe(true);
    expect(brandIconSvg("slack")).toContain("<svg");
    expect(brandIconDataUri("nope")).toBeNull();
  });
  it("fixture connectors carry icon_url so screenshots show real glyphs", () => {
    for (const c of FIXTURE_CONNECTORS) expect(c.icon_url?.startsWith("data:")).toBe(true);
  });
});

describe("additive contract fields in the fixture client", () => {
  it("returns org_name, signed_in_count, tools added/removed, account_label and user_label", async () => {
    const api = createFixtureConnectorsApi({ latencyMs: 0 });
    const list = await api.list();
    expect(list.org_name).toBe("Acme Analytics");
    const jira = list.connectors.find((c) => c.id === "con_jira")!;
    expect(jira.signed_in_count).toBe(3);
    expect(jira.my_state?.account_label).toBe("eli@acme-analytics.com");
    const slack = list.connectors.find((c) => c.id === "con_slack")!;
    expect([slack.tools_added, slack.tools_removed]).toEqual([3, 1]);
    const calls = await api.activity("con_jira");
    expect(calls.every((c) => typeof c.user_label === "string")).toBe(true);
    // Sign-out adjusts the count; acknowledging new tools clears the delta.
    await api.signOut("con_jira");
    expect((await api.list()).connectors.find((c) => c.id === "con_jira")!.signed_in_count).toBe(2);
    const refreshed = await api.refreshTools("con_slack");
    expect(refreshed.tools_added).toBeNull();
  });
});

describe("review copy helpers", () => {
  it("says how many members are signed in", () => {
    expect(describeSignedInMembers(3)).toBe("3 members are signed in.");
    expect(describeSignedInMembers(1)).toBe("1 member is signed in.");
    expect(describeSignedInMembers(0)).toBe("No one is signed in.");
    expect(describeSignedInMembers(null)).toBe("");
    expect(describeSignedInMembers(undefined)).toBe("");
  });
  it("names the caller from the label, 'you' for the caller, and never a raw hash", () => {
    expect(describeCaller({ user_id: "user_maya", user_label: "maya@acme.com" }, FIXTURE_ME)).toMatchObject({ label: "maya@acme.com", you: false });
    expect(describeCaller({ user_id: FIXTURE_ME, user_label: "eli@acme.com" }, FIXTURE_ME)).toMatchObject({ label: "eli@acme.com (you)", you: true });
    expect(describeCaller({ user_id: FIXTURE_ME, user_label: null }, FIXTURE_ME)).toMatchObject({ label: "you" });
    const prod = describeCaller({ user_id: "user_2NNEqL2nrIRdJ194ndJqAHwEfxC", user_label: null }, null);
    expect(prod.label).toBe("2NNEqL…");
    expect(prod.title).toBe("user_2NNEqL2nrIRdJ194ndJqAHwEfxC");
  });
  it("describes the tools-changed banner from the gateway's counts when present", () => {
    expect(describeToolsChanged({ tools_added: 3, tools_removed: 1 }, 3)).toBe("3 added · 1 removed since last check");
    expect(describeToolsChanged({ tools_added: 2, tools_removed: 0 }, 2)).toBe("2 added since last check");
    expect(describeToolsChanged({ tools_added: null, tools_removed: null }, 1)).toBe("1 new tool since last check");
    expect(describeToolsChanged({}, 4)).toBe("4 new tools since last check");
  });
  it("summarizes the org policy for the collapsed row", () => {
    expect(describePolicy({ allow_personal: true, allowed_hosts: [], updated_at: "" })).toBe("Members can add personal connectors · any host");
    expect(describePolicy({ allow_personal: true, allowed_hosts: ["*.atlassian.com"], updated_at: "" })).toBe("Members can add personal connectors · *.atlassian.com");
    expect(describePolicy({ allow_personal: true, allowed_hosts: ["a", "b"], updated_at: "" })).toBe("Members can add personal connectors · 2 allowed hosts");
    expect(describePolicy({ allow_personal: false, allowed_hosts: [], updated_at: "" })).toBe("Members can't add personal connectors");
  });
  it("deep-links the chat panel row into the settings drawer", () => {
    expect(connectorDeepLink("/settings/connectors", "con_jira")).toBe("/settings/connectors?open=con_jira");
    expect(connectorDeepLink("/settings/connectors?fixture=1", "con_jira")).toBe("/settings/connectors?fixture=1&open=con_jira");
  });
});
