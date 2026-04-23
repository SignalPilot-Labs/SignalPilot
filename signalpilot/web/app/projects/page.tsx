"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Plus,
  Trash2,
  Loader2,
  FolderOpen,
  Database,
  Clock,
  ArrowRight,
  Upload,
  GitBranch,
  Cloud,
} from "lucide-react";
import { getProjects, createProject, deleteProject, getConnections, discoverDbtCloudProjects } from "@/lib/api";
import type { ProjectInfo, ConnectionInfo } from "@/lib/types";
import { EmptyState } from "@/components/ui/empty-states";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";
import { TimeAgo } from "@/components/ui/time-ago";

/* ── Empty icon for projects ── */
function EmptyProject({ className = "" }: { className?: string }) {
  return (
    <svg width="48" height="48" viewBox="0 0 48 48" fill="none" className={className}>
      <path d="M4 12L4 40H44V12H24L20 6H4V12Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="miter" fill="none" />
      <line x1="16" y1="24" x2="32" y2="24" stroke="currentColor" strokeWidth="1" opacity="0.4" />
      <line x1="16" y1="30" x2="28" y2="30" stroke="currentColor" strokeWidth="1" opacity="0.4" />
    </svg>
  );
}

const NAME_PATTERN = /^[a-zA-Z0-9_-]+$/;

export default function ProjectsPage() {
  const { toast } = useToast();
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [showGithub, setShowGithub] = useState(false);
  const [showDbtCloud, setShowDbtCloud] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createForm, setCreateForm] = useState({ name: "", connection_name: "" });
  const [importForm, setImportForm] = useState({ name: "", path: "", connection_name: "", mode: "link" as "link" | "copy" });
  const [githubForm, setGithubForm] = useState({ name: "", git_url: "", git_branch: "main", connection_name: "" });
  const [dbtCloudForm, setDbtCloudForm] = useState({ token: "", account_id: "" });
  const [dbtCloudProjects, setDbtCloudProjects] = useState<{ id: number; name: string; git_url: string | null }[]>([]);
  const [dbtCloudSelected, setDbtCloudSelected] = useState<{ id: number; name: string; git_url: string } | null>(null);
  const [dbtCloudConnection, setDbtCloudConnection] = useState("");
  const [dbtCloudFetching, setDbtCloudFetching] = useState(false);

  const refresh = useCallback(() => {
    getProjects().then(setProjects).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    getConnections().then(setConnections).catch(() => {});
    const i = setInterval(refresh, 10000);
    return () => clearInterval(i);
  }, [refresh]);

  async function handleCreate() {
    if (!createForm.name || !NAME_PATTERN.test(createForm.name)) {
      toast("name must match [a-zA-Z0-9_-]", "error");
      return;
    }
    if (!createForm.connection_name) {
      toast("select a connection", "error");
      return;
    }
    setCreating(true);
    try {
      const p = await createProject({
        name: createForm.name,
        connection_name: createForm.connection_name,
        source: "new",
      });
      setProjects((prev) => [p, ...prev]);
      setShowCreate(false);
      setCreateForm({ name: "", connection_name: "" });
    } catch (e) { toast(String(e), "error"); }
    finally { setCreating(false); }
  }

  async function handleImport() {
    if (!importForm.name || !NAME_PATTERN.test(importForm.name)) {
      toast("name must match [a-zA-Z0-9_-]", "error");
      return;
    }
    if (!importForm.path) {
      toast("path is required", "error");
      return;
    }
    if (!importForm.connection_name) {
      toast("select a connection", "error");
      return;
    }
    setCreating(true);
    try {
      const p = await createProject({
        name: importForm.name,
        local_path: importForm.path,
        connection_name: importForm.connection_name,
        source: "local",
        link_mode: importForm.mode,
      });
      setProjects((prev) => [p, ...prev]);
      setShowImport(false);
      setImportForm({ name: "", path: "", connection_name: "", mode: "link" });
    } catch (e) { toast(String(e), "error"); }
    finally { setCreating(false); }
  }

  async function handleGithub() {
    if (!githubForm.name || !NAME_PATTERN.test(githubForm.name)) {
      toast("name must match [a-zA-Z0-9_-]", "error");
      return;
    }
    if (!githubForm.git_url) {
      toast("repo url is required", "error");
      return;
    }
    if (!githubForm.connection_name) {
      toast("select a connection", "error");
      return;
    }
    setCreating(true);
    try {
      const p = await createProject({
        name: githubForm.name,
        git_url: githubForm.git_url,
        git_branch: githubForm.git_branch || "main",
        connection_name: githubForm.connection_name,
        source: "github",
      });
      setProjects((prev) => [p, ...prev]);
      setShowGithub(false);
      setGithubForm({ name: "", git_url: "", git_branch: "main", connection_name: "" });
      toast(`cloned ${githubForm.git_url}`, "success");
    } catch (e) { toast(String(e), "error"); }
    finally { setCreating(false); }
  }

  async function handleDbtCloudFetch() {
    if (!dbtCloudForm.token || !dbtCloudForm.account_id) {
      toast("token and account id are required", "error");
      return;
    }
    setDbtCloudFetching(true);
    try {
      const projects = await discoverDbtCloudProjects(dbtCloudForm.token, dbtCloudForm.account_id);
      setDbtCloudProjects(projects);
      if (projects.length === 0) toast("no projects found in this account", "error");
    } catch (e) { toast(String(e), "error"); }
    finally { setDbtCloudFetching(false); }
  }

  async function handleDbtCloudImport() {
    if (!dbtCloudSelected) {
      toast("select a project", "error");
      return;
    }
    if (!dbtCloudConnection) {
      toast("select a connection", "error");
      return;
    }
    setCreating(true);
    try {
      const name = dbtCloudSelected.name.replace(/[^a-zA-Z0-9_-]/g, "-").toLowerCase();
      const p = await createProject({
        name,
        git_url: dbtCloudSelected.git_url,
        git_branch: "main",
        connection_name: dbtCloudConnection,
        source: "dbt-cloud",
        dbt_cloud_account_id: dbtCloudForm.account_id,
        dbt_cloud_project_id: String(dbtCloudSelected.id),
      });
      setProjects((prev) => [p, ...prev]);
      setShowDbtCloud(false);
      setDbtCloudForm({ token: "", account_id: "" });
      setDbtCloudProjects([]);
      setDbtCloudSelected(null);
      setDbtCloudConnection("");
      toast(`imported ${p.name} from dbt Cloud`, "success");
    } catch (e) { toast(String(e), "error"); }
    finally { setCreating(false); }
  }

  async function handleDelete(name: string) {
    try {
      await deleteProject(name);
      setProjects((prev) => prev.filter((p) => p.name !== name));
    } catch (e) { toast(String(e), "error"); }
  }

  return (
    <div className="p-8 animate-fade-in">
      <PageHeader
        title="projects"
        subtitle="dbt"
        description="dbt project management"
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowDbtCloud(true)}
              className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
            >
              <Cloud className="w-3.5 h-3.5" /> dbt cloud
            </button>
            <button
              onClick={() => setShowGithub(true)}
              className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
            >
              <GitBranch className="w-3.5 h-3.5" /> github
            </button>
            <button
              onClick={() => setShowImport(true)}
              className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
            >
              <Upload className="w-3.5 h-3.5" /> import local
            </button>
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90"
            >
              <Plus className="w-3.5 h-3.5" /> new project
            </button>
          </div>
        }
      />

      <TerminalBar
        path="projects --list"
        status={<StatusDot status={projects.length > 0 ? "healthy" : "unknown"} size={4} pulse={false} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">total: <code className="text-[12px] text-[var(--color-text)]">{projects.length}</code></span>
          <span className="text-[var(--color-text-dim)]">active: <code className="text-[12px] text-[var(--color-success)]">{projects.filter(p => p.status === "active").length}</code></span>
        </div>
      </TerminalBar>

      {/* Create dialog */}
      {showCreate && (
        <div className="mb-6 border border-[var(--color-border)] bg-[var(--color-bg-card)] animate-scale-in overflow-hidden">
          <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center gap-2">
            <FolderOpen className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">new project</span>
          </div>
          <div className="p-5">
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">name</label>
                <input
                  type="text"
                  placeholder="my-dbt-project"
                  value={createForm.name}
                  onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                />
              </div>
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">connection</label>
                <select
                  value={createForm.connection_name}
                  onChange={(e) => setCreateForm({ ...createForm, connection_name: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
                >
                  <option value="">select connection</option>
                  {connections.map((c) => (
                    <option key={c.name} value={c.name}>{c.name} ({c.db_type})</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={handleCreate}
                disabled={creating}
                className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
              >
                {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                create
              </button>
              <button
                onClick={() => setShowCreate(false)}
                className="px-4 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
              >
                cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Import dialog */}
      {showImport && (
        <div className="mb-6 border border-[var(--color-border)] bg-[var(--color-bg-card)] animate-scale-in overflow-hidden">
          <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center gap-2">
            <Upload className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">import local project</span>
          </div>
          <div className="p-5">
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">name</label>
                <input
                  type="text"
                  placeholder="my-project"
                  value={importForm.name}
                  onChange={(e) => setImportForm({ ...importForm, name: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                />
              </div>
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">path</label>
                <input
                  type="text"
                  placeholder="/home/user/my-dbt-project"
                  value={importForm.path}
                  onChange={(e) => setImportForm({ ...importForm, path: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide font-mono"
                />
              </div>
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">connection</label>
                <select
                  value={importForm.connection_name}
                  onChange={(e) => setImportForm({ ...importForm, connection_name: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
                >
                  <option value="">select connection</option>
                  {connections.map((c) => (
                    <option key={c.name} value={c.name}>{c.name} ({c.db_type})</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="mb-4">
              <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">mode</label>
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-xs text-[var(--color-text-muted)] cursor-pointer">
                  <input
                    type="radio"
                    name="import-mode"
                    checked={importForm.mode === "link"}
                    onChange={() => setImportForm({ ...importForm, mode: "link" })}
                    className="accent-[var(--color-text)]"
                  />
                  link (reference in place)
                </label>
                <label className="flex items-center gap-2 text-xs text-[var(--color-text-muted)] cursor-pointer">
                  <input
                    type="radio"
                    name="import-mode"
                    checked={importForm.mode === "copy"}
                    onChange={() => setImportForm({ ...importForm, mode: "copy" })}
                    className="accent-[var(--color-text)]"
                  />
                  copy (managed copy)
                </label>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={handleImport}
                disabled={creating}
                className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
              >
                {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                import
              </button>
              <button
                onClick={() => setShowImport(false)}
                className="px-4 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
              >
                cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* GitHub dialog */}
      {showGithub && (
        <div className="mb-6 border border-[var(--color-border)] bg-[var(--color-bg-card)] animate-scale-in overflow-hidden">
          <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center gap-2">
            <GitBranch className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">import from github</span>
          </div>
          <div className="p-5">
            <div className="grid grid-cols-4 gap-4 mb-4">
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">name</label>
                <input
                  type="text"
                  placeholder="my-project"
                  value={githubForm.name}
                  onChange={(e) => setGithubForm({ ...githubForm, name: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                />
              </div>
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">repo url</label>
                <input
                  type="text"
                  placeholder="https://github.com/org/repo.git"
                  value={githubForm.git_url}
                  onChange={(e) => setGithubForm({ ...githubForm, git_url: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide font-mono"
                />
              </div>
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">branch</label>
                <input
                  type="text"
                  placeholder="main"
                  value={githubForm.git_branch}
                  onChange={(e) => setGithubForm({ ...githubForm, git_branch: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                />
              </div>
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">connection</label>
                <select
                  value={githubForm.connection_name}
                  onChange={(e) => setGithubForm({ ...githubForm, connection_name: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
                >
                  <option value="">select connection</option>
                  {connections.map((c) => (
                    <option key={c.name} value={c.name}>{c.name} ({c.db_type})</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={handleGithub}
                disabled={creating}
                className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
              >
                {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <GitBranch className="w-3.5 h-3.5" />}
                clone
              </button>
              <button
                onClick={() => setShowGithub(false)}
                className="px-4 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
              >
                cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* dbt Cloud dialog */}
      {showDbtCloud && (
        <div className="mb-6 border border-[var(--color-border)] bg-[var(--color-bg-card)] animate-scale-in overflow-hidden">
          <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center gap-2">
            <Cloud className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">import from dbt cloud</span>
          </div>
          <div className="p-5">
            {/* Step 1: token + account */}
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">api token</label>
                <input
                  type="password"
                  placeholder="dbtc_..."
                  value={dbtCloudForm.token}
                  onChange={(e) => setDbtCloudForm({ ...dbtCloudForm, token: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide font-mono"
                />
              </div>
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">account id</label>
                <input
                  type="text"
                  placeholder="12345"
                  value={dbtCloudForm.account_id}
                  onChange={(e) => setDbtCloudForm({ ...dbtCloudForm, account_id: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                />
              </div>
              <div className="flex items-end">
                <button
                  onClick={handleDbtCloudFetch}
                  disabled={dbtCloudFetching}
                  className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
                >
                  {dbtCloudFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Database className="w-3.5 h-3.5" />}
                  fetch projects
                </button>
              </div>
            </div>

            {/* Step 2: select project + connection */}
            {dbtCloudProjects.length > 0 && (
              <div className="border-t border-[var(--color-border)] pt-4 mt-4">
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-2 tracking-wider">select project</label>
                <div className="space-y-1 mb-4 max-h-48 overflow-y-auto">
                  {dbtCloudProjects.map((p) => (
                    <label
                      key={p.id}
                      className={`flex items-center gap-3 px-3 py-2 cursor-pointer text-xs border transition-colors ${
                        dbtCloudSelected?.id === p.id
                          ? "border-[var(--color-text)] bg-[var(--color-bg-input)]"
                          : "border-transparent hover:bg-[var(--color-bg-input)]"
                      }`}
                    >
                      <input
                        type="radio"
                        name="dbt-cloud-project"
                        checked={dbtCloudSelected?.id === p.id}
                        onChange={() => p.git_url ? setDbtCloudSelected({ id: p.id, name: p.name, git_url: p.git_url }) : null}
                        disabled={!p.git_url}
                        className="accent-[var(--color-text)]"
                      />
                      <span className={p.git_url ? "" : "text-[var(--color-text-dim)] line-through"}>{p.name}</span>
                      <span className="text-[var(--color-text-dim)] font-mono ml-auto">{p.git_url || "no repo"}</span>
                    </label>
                  ))}
                </div>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">connection</label>
                    <select
                      value={dbtCloudConnection}
                      onChange={(e) => setDbtCloudConnection(e.target.value)}
                      className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
                    >
                      <option value="">select connection</option>
                      {connections.map((c) => (
                        <option key={c.name} value={c.name}>{c.name} ({c.db_type})</option>
                      ))}
                    </select>
                  </div>
                </div>
                <button
                  onClick={handleDbtCloudImport}
                  disabled={creating || !dbtCloudSelected}
                  className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
                >
                  {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Cloud className="w-3.5 h-3.5" />}
                  import
                </button>
              </div>
            )}

            <div className="flex items-center gap-3 mt-3">
              <button
                onClick={() => { setShowDbtCloud(false); setDbtCloudProjects([]); setDbtCloudSelected(null); }}
                className="px-4 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
              >
                cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Project grid */}
      {projects.length === 0 ? (
        <EmptyState
          icon={EmptyProject}
          title="no projects"
          description="create or import a dbt project to get started"
          action={
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider"
            >
              <Plus className="w-3.5 h-3.5" /> create first project
            </button>
          }
        />
      ) : (
        <div className="grid grid-cols-3 gap-px bg-[var(--color-border)] stagger-fade-in">
          {projects.map((proj) => (
            <Link
              key={proj.id}
              href={`/projects/${proj.name}`}
              className="group block bg-[var(--color-bg-card)] hover:bg-[var(--color-bg-hover)] transition-all card-accent-top overflow-hidden"
            >
              {/* Card header */}
              <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
                <div className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: proj.status === "active" ? "var(--color-success)" : proj.status === "error" ? "var(--color-error)" : "var(--color-text-dim)", opacity: proj.status === "active" ? 1 : 0.4 }} />
                  <span className="w-2 h-2 rounded-full bg-[var(--color-text-dim)] opacity-20" />
                  <span className="w-2 h-2 rounded-full bg-[var(--color-text-dim)] opacity-10" />
                </div>
                <span className="text-[11px] text-[var(--color-text-dim)] tracking-[0.15em] uppercase">{proj.status}</span>
                <div className="flex items-center gap-1">
                  <ArrowRight className="w-3 h-3 text-[var(--color-text-dim)] opacity-0 group-hover:opacity-100 transition-opacity" />
                  <button
                    onClick={(e) => {
                      e.preventDefault();
                      handleDelete(proj.name);
                    }}
                    className="opacity-0 group-hover:opacity-100 p-0.5 text-[var(--color-text-dim)] hover:text-[var(--color-error)] transition-all"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              </div>

              <div className="p-4 space-y-2.5">
                {/* Name */}
                <div className="flex items-center gap-2">
                  <StatusDot
                    status={proj.status === "active" ? "healthy" : proj.status === "error" ? "error" : "warning"}
                    size={4}
                    pulse={false}
                  />
                  <span className="text-xs text-[var(--color-text)] font-bold uppercase tracking-wider group-hover:text-white transition-colors">
                    {proj.name}
                  </span>
                </div>

                {/* Info grid */}
                <div className="grid grid-cols-2 gap-2 text-[12px] text-[var(--color-text-dim)] tracking-wider">
                  <div className="flex items-center gap-1.5">
                    <Database className="w-3 h-3" strokeWidth={1.5} />
                    <span className="truncate">{proj.connection_name}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="px-1.5 py-0.5 border border-[var(--color-border)] text-[11px]">{proj.db_type}</span>
                  </div>
                  <div className="flex items-center gap-1.5 tabular-nums">
                    <span>{proj.model_count} models</span>
                  </div>
                  {proj.last_scanned_at && (
                    <div className="flex items-center gap-1.5">
                      <Clock className="w-3 h-3" strokeWidth={1.5} />
                      <TimeAgo timestamp={proj.last_scanned_at} live className="tabular-nums" />
                    </div>
                  )}
                </div>

                {/* Badges */}
                <div className="flex items-center gap-2 pt-1">
                  <span className="px-1.5 py-0.5 border border-[var(--color-border)] text-[11px] tracking-wider">
                    {proj.storage}
                  </span>
                  <span className="px-1.5 py-0.5 border border-[var(--color-border)] text-[11px] tracking-wider">
                    {proj.source}
                  </span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
