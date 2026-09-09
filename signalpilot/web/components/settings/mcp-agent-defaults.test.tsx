import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { McpAgentDefaults } from "~/lib/types";
import { McpAgentDefaultsSettings } from "./mcp-agent-defaults";

const api = vi.hoisted(() => ({
  getMcpAgentDefaults: vi.fn(), getWorkspaceProjects: vi.fn(), getConnections: vi.fn(), updateMcpAgentDefaults: vi.fn(),
  auth: { activeOrgId: "org-a", activeOrgName: "Example organization" },
}));
vi.mock("~/lib/api", () => api);
vi.mock("~/lib/auth-context", () => ({ useAppAuth: () => api.auth }));
const empty: McpAgentDefaults = { mcp_agent_default_project_id: null, mcp_agent_default_connection_name: null, mcp_agent_default_branch: null };

describe("MCP agent defaults", () => {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    vi.clearAllMocks();
    api.auth.activeOrgId = "org-a";
    api.getMcpAgentDefaults.mockResolvedValue(empty);
    api.getWorkspaceProjects.mockResolvedValue({ projects: [{ id: "p1", name: "warehouse", display_name: "Warehouse", status: "active", default_branch: "main" }] });
    api.getConnections.mockResolvedValue([{ name: "warehouse-db" }]);
    api.updateMcpAgentDefaults.mockImplementation(async (value) => value);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => { act(() => root.unmount()); container.remove(); });
  async function render() { await act(async () => { root.render(<McpAgentDefaultsSettings />); }); }
  function select(id: string, value: string) {
    act(() => {
      const element = container.querySelector<HTMLSelectElement>(id)!;
      element.value = value;
      element.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }
  async function submit() {
    await act(async () => { container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  }
  it("does not choose defaults automatically and saves only explicit selections", async () => {
    await render();
    expect(container.querySelector<HTMLSelectElement>("#mcp-agent-project")!.value).toBe("");
    expect(container.querySelector<HTMLSelectElement>("#mcp-agent-connection")!.value).toBe("");
    select("#mcp-agent-project", "p1");
    expect(container.querySelector<HTMLButtonElement>('[type="submit"]')!.disabled).toBe(true);
    select("#mcp-agent-connection", "warehouse-db");
    await submit();
    expect(api.updateMcpAgentDefaults).toHaveBeenCalledWith({ ...empty, mcp_agent_default_project_id: "p1", mcp_agent_default_connection_name: "warehouse-db" });
    expect(container.textContent).toContain("Agent defaults saved for this organization.");
    expect(container.textContent).toContain("latest saved project revision");
  });
  it("offers retry after loading fails", async () => {
    api.getMcpAgentDefaults.mockRejectedValueOnce(new Error("denied"));
    await render();
    expect(container.querySelector('[role="alert"]')!.textContent).toContain("Unable to load");
    await act(async () => { container.querySelector("button")!.click(); });
    expect(container.querySelector("form")).not.toBeNull();
  });
  it("shows a save error without falsely confirming saved defaults", async () => {
    await render();
    api.updateMcpAgentDefaults.mockRejectedValueOnce(new Error("denied"));
    await submit();
    expect(container.textContent).toContain("Unable to save defaults");
    expect(container.textContent).not.toContain("Agent defaults saved");
  });
  it("discards responses from the previously selected organization", async () => {
    let finish!: (value: typeof empty) => void;
    api.getMcpAgentDefaults.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    await render();
    api.auth.activeOrgId = "org-b";
    await render();
    await act(async () => { finish({ ...empty, mcp_agent_default_project_id: "old-org-project" } as typeof empty); });
    expect(container.querySelector<HTMLSelectElement>("#mcp-agent-project")!.value).toBe("");
    expect(container.textContent).not.toContain("Saved project unavailable");
  });
});
