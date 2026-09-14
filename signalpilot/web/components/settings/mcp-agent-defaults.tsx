"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Bot } from "lucide-react";
import { useAppAuth } from "~/lib/auth-context";
import { getConnections, getMcpAgentDefaults, getWorkspaceProjects, updateMcpAgentDefaults } from "~/lib/api";
import type { ConnectionInfo, McpAgentDefaults, WorkspaceProjectInfo } from "~/lib/types";
import { SectionHeader } from "~/components/ui/section-header";

const EMPTY: McpAgentDefaults = {
  mcp_agent_default_project_id: null,
  mcp_agent_default_connection_name: null,
  mcp_agent_default_branch: null,
};
const inputClass = "w-full mt-1 rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] disabled:opacity-50";

export function McpAgentDefaultsSettings() {
  const { activeOrgId, activeOrgName } = useAppAuth();
  return <section className="mb-8">
    <SectionHeader icon={Bot} title="agent defaults" />
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-5">
      {activeOrgId ? <DefaultsForm key={activeOrgId} orgName={activeOrgName} /> :
        <p className="text-sm text-[var(--color-text-dim)]">Select an organization to configure its agent defaults.</p>}
    </div>
  </section>;
}

function DefaultsForm({ orgName }: { orgName: string | null }) {
  const [defaults, setDefaults] = useState<McpAgentDefaults>(EMPTY);
  const [projects, setProjects] = useState<WorkspaceProjectInfo[]>([]);
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [reload, setReload] = useState(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([getMcpAgentDefaults(), getWorkspaceProjects("active"), getConnections()])
      .then(([settings, projectList, connectionList]) => {
        if (cancelled) return;
        setDefaults(settings);
        setProjects(projectList.projects.filter((project) => project.status === "active"));
        setConnections(connectionList);
        setLoaded(true);
      })
      .catch(() => { if (!cancelled) setError("Unable to load agent defaults. Organization admin access may be required."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; mounted.current = false; };
  }, [reload]);

  const project = projects.find((item) => item.id === defaults.mcp_agent_default_project_id);
  const connectionExists = connections.some((item) => item.name === defaults.mcp_agent_default_connection_name);
  const unavailable = Boolean((defaults.mcp_agent_default_project_id && !project) ||
    (defaults.mcp_agent_default_connection_name && !connectionExists));
  const configured = Boolean(defaults.mcp_agent_default_project_id && defaults.mcp_agent_default_connection_name);
  const cleared = !defaults.mcp_agent_default_project_id && !defaults.mcp_agent_default_connection_name;
  function change(value: Partial<McpAgentDefaults>) {
    setDefaults((current) => ({ ...current, ...value }));
    setSaved(false);
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving || unavailable || (!configured && !cleared)) return;
    setSaving(true); setError(null); setSaved(false);
    try {
      const result = await updateMcpAgentDefaults({ ...defaults,
        mcp_agent_default_branch: configured ? defaults.mcp_agent_default_branch?.trim() || null : null });
      if (mounted.current) { setDefaults(result); setSaved(true); }
    } catch {
      if (mounted.current) setError("Unable to save defaults. Check the selected project and connection and your organization admin access.");
    } finally {
      if (mounted.current) setSaving(false);
    }
  }
  if (loading) return <p role="status" className="text-sm text-[var(--color-text-dim)]">Loading agent defaults…</p>;
  if (!loaded) return <div role="alert" className="text-sm">
    <p>{error}</p><button type="button" onClick={() => setReload((n) => n + 1)} className="underline mt-2">Retry</button>
  </div>;
  return <form onSubmit={save} className="space-y-4">
    <p className="text-sm text-[var(--color-text-dim)]">
      Choose the project and connection shared by MCP agents in {orgName || "this organization"}.
      Once saved, ask SignalPilot to work using just your task. Runs use the same agent, project branch, and sandbox configuration as Chats.
      You can override these defaults for an individual run.
    </p>
    <fieldset disabled={saving} className="space-y-4">
      <label className="block text-sm" htmlFor="mcp-agent-project">Project
        <select id="mcp-agent-project" className={inputClass} value={defaults.mcp_agent_default_project_id || ""}
          onChange={(e) => change({ mcp_agent_default_project_id: e.target.value || null, mcp_agent_default_branch: null })}>
          <option value="">Choose a project</option>
          {defaults.mcp_agent_default_project_id && !project && <option value={defaults.mcp_agent_default_project_id}>Saved project unavailable</option>}
          {projects.map((item) => <option key={item.id} value={item.id}>{item.display_name || item.name}</option>)}
        </select>
      </label>
      <label className="block text-sm" htmlFor="mcp-agent-connection">Connection
        <select id="mcp-agent-connection" className={inputClass} value={defaults.mcp_agent_default_connection_name || ""}
          onChange={(e) => change({ mcp_agent_default_connection_name: e.target.value || null })}>
          <option value="">Choose a connection</option>
          {defaults.mcp_agent_default_connection_name && !connectionExists && <option value={defaults.mcp_agent_default_connection_name}>Saved connection unavailable</option>}
          {connections.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
        </select>
      </label>
      <label className="block text-sm" htmlFor="mcp-agent-branch">Branch (optional)
        <input id="mcp-agent-branch" className={inputClass} value={defaults.mcp_agent_default_branch || ""} maxLength={100}
          disabled={!project || saving} placeholder={project?.default_branch || "Project default branch"}
          onChange={(e) => change({ mcp_agent_default_branch: e.target.value || null })} />
        <span className="mt-1 block text-xs text-[var(--color-text-dim)]">Leave blank to use the project’s default branch.</span>
      </label>
      {(!projects.length || !connections.length) && <p className="text-sm text-[var(--color-text-dim)]">Add an active project and a connection before configuring task-only agent runs.</p>}
      {unavailable && <p role="alert" className="text-sm text-[var(--color-error)]">A saved project or connection is no longer available. Choose a replacement or clear the defaults.</p>}
      {!configured && !cleared && <p className="text-sm text-[var(--color-text-dim)]">Choose both a project and a connection.</p>}
      <div className="flex items-center gap-4">
        <button type="submit" disabled={unavailable || (!configured && !cleared)} className="rounded-[10px] border border-[var(--color-border)] px-4 py-2 text-sm disabled:opacity-50">
          {saving ? "Saving…" : "Save defaults"}
        </button>
        <button type="button" onClick={() => change(EMPTY)} className="text-sm underline">Clear selections</button>
      </div>
    </fieldset>
    {error && <p role="alert" className="text-sm text-[var(--color-error)]">{error}</p>}
    {saved && <p role="status" className="text-sm text-[var(--color-success)]">Agent defaults saved for this organization.</p>}
  </form>;
}
