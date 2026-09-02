import { describe, expect, it } from "vitest";
import { createFixtureConnectorsApi } from "~/lib/mcp-connectors-fixture-client";

const api = () => createFixtureConnectorsApi({ latencyMs: 0 });

describe("fixture connectors client (contract shape)", () => {
  it("lists the seeded connectors with policy and admin flag", async () => {
    const response = await api().list();
    expect(response.connectors.map((c) => c.id)).toEqual([
      "con_jira",
      "con_snowflake_docs",
      "con_slack",
      "con_github",
      "con_linear",
    ]);
    expect(response.policy.allow_personal).toBe(true);
    expect(response.is_admin).toBe(true);
  });

  it("creates a personal connector from a probed URL with R3 tool defaults", async () => {
    const client = api();
    const probe = await client.probe({ url: "https://docs.vendor.example/mcp" });
    expect(probe.auth).toBe("key");
    const created = await client.create({ scope: "personal", name: "Vendor docs", url: "https://docs.vendor.example/mcp", auth: "key", headers: { "X-API-Key": "k" } });
    expect(created.slug).toBe("vendor_docs");
    expect(created.status).toBe("connected");
    expect(created.header_keys).toEqual([{ name: "X-API-Key", has_value: true }]);
    const detail = await client.get(created.id);
    expect(detail.tools.every((t) => t.enabled === Boolean(t.annotations.read_only_hint))).toBe(true);
  });

  it("suffixes a personal slug that collides with an org slug and rejects duplicates", async () => {
    const client = api();
    const mine = await client.create({ scope: "personal", name: "Jira", url: "https://jira.example/mcp" });
    expect(mine.slug).toBe("jira_mine");
    await expect(client.create({ scope: "personal", name: "GitHub", command: "npx" })).rejects.toThrow(/already have/);
  });

  it("lets a member turn org tools off for themselves only", async () => {
    const client = createFixtureConnectorsApi({ latencyMs: 0, isAdmin: false });
    const detail = await client.updateTools("con_jira", { tools: { search_issues: { enabled: false, policy: "off" } } });
    expect(detail.tools.find((t) => t.name === "search_issues")?.enabled).toBe(true);
    expect(detail.my_state?.disabled_tools).toEqual(["search_issues"]);
    await expect(client.patch("con_jira", { enabled: false })).rejects.toThrow(/403/);
  });

  it("signs in and out, and toggles the member switch", async () => {
    const client = api();
    const result = await client.signIn("con_linear");
    expect(result.outcome).toBe("signed_in");
    const me = await client.updateMe("con_jira", { enabled: false });
    expect(me.enabled).toBe(false);
    const out = await client.signOut("con_jira");
    expect(out.signed_in).toBe(false);
  });

  it("writes secrets without ever returning them", async () => {
    const client = api();
    const updated = await client.updateSecrets("con_github", { env: { GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_x" } });
    expect(JSON.stringify(updated)).not.toContain("ghp_x");
    expect(updated.my_state?.has_key).toBe(true);
    const cleared = await client.deleteSecret("con_github", "GITHUB_PERSONAL_ACCESS_TOKEN");
    expect(cleared.my_state?.has_key).toBe(false);
  });

  it("clears the tools-changed state after the review acknowledges new tools", async () => {
    const client = api();
    const detail = await client.refreshTools("con_slack");
    expect(detail.status).toBe("connected");
    expect(detail.tools.some((t) => t.is_new)).toBe(false);
  });
});
