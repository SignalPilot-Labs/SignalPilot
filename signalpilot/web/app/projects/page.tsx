"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import {
  Plus,
  Loader2,
  FolderOpen,
  Database,
  Clock,
  ArrowRight,
  FileText,
  HardDrive,
  GitBranch,
  Cloud,
  Server,
  Play,
  Square,
  Code,
} from "lucide-react";
import { getWorkspaceProjects, createWorkspaceProject, getConnections } from "@/lib/api";
import type { WorkspaceProjectInfo, ConnectionInfo } from "@/lib/types";
import { EmptyState } from "@/components/ui/empty-states";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";
import { TimeAgo } from "@/components/ui/time-ago";

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
type Source = "managed" | "github" | "dbt-cloud";

const SOURCE_LABELS: Record<Source, { label: string; icon: typeof Server; desc: string }> = {
  managed: { label: "new project", icon: Server, desc: "empty project stored on S3" },
  github: { label: "from github", icon: GitBranch, desc: "import from a github repo" },
  "dbt-cloud": { label: "from dbt cloud", icon: Cloud, desc: "connect a dbt cloud project" },
};

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function sourceIcon(source: string) {
  if (source === "github") return <GitBranch className="w-3 h-3" strokeWidth={1.5} />;
  if (source === "dbt-cloud") return <Cloud className="w-3 h-3" strokeWidth={1.5} />;
  return <Server className="w-3 h-3" strokeWidth={1.5} />;
}

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300";

export default function ProjectsPage() {
  const { toast } = useToast();
  const [projects, setProjects] = useState<WorkspaceProjectInfo[]>([]);
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [source, setSource] = useState<Source>("managed");
  const [form, setForm] = useState({
    name: "",
    display_name: "",
    description: "",
    connection_name: "",
    git_remote: "",
  });

  // IDE state
  const [ideStatus, setIdeStatus] = useState<"closed" | "starting" | "running">("closed");
  const [ideUrl, setIdeUrl] = useState<string | null>(null);
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(() => {
    getWorkspaceProjects("active")
      .then((res) => setProjects(res.projects))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    getConnections().then(setConnections).catch(() => {});
    checkIdeSession();
    const i = setInterval(refresh, 10000);
    return () => {
      clearInterval(i);
      if (pingRef.current) clearInterval(pingRef.current);
    };
  }, [refresh]);

  async function checkIdeSession() {
    try {
      const r = await fetch(`${GATEWAY_URL}/api/notebook-sessions`, { headers: await getAuthHeaders() });
      if (r.ok) {
        const session = await r.json();
        if (session && session.status === "running") {
          setIdeStatus("running");
          const token = session.access_token ? `?access_token=${session.access_token}` : "";
          setIdeUrl(`${GATEWAY_URL}${session.proxy_base}${token}`);
          startPing();
        }
      }
    } catch {}
  }

  async function launchIde() {
    setIdeStatus("starting");
    try {
      const r = await fetch(`${GATEWAY_URL}/api/notebook-sessions`, {
        method: "POST",
        headers: { ...(await getAuthHeaders()), "Content-Type": "application/json" },
        body: JSON.stringify({ branch: "main" }),
      });
      if (!r.ok) {
        toast(`Failed to start IDE: ${await r.text()}`, "error");
        setIdeStatus("closed");
        return;
      }
      const session = await r.json();
      setIdeStatus("running");
      const token = session.access_token ? `?access_token=${session.access_token}` : "";
      setIdeUrl(`${GATEWAY_URL}${session.proxy_base}${token}`);
      startPing();
    } catch (e) {
      toast(String(e), "error");
      setIdeStatus("closed");
    }
  }

  async function stopIde() {
    try {
      await fetch(`${GATEWAY_URL}/api/notebook-sessions`, { method: "DELETE", headers: await getAuthHeaders() });
    } catch {}
    setIdeStatus("closed");
    setIdeUrl(null);
    if (pingRef.current) { clearInterval(pingRef.current); pingRef.current = null; }
  }

  function startPing() {
    if (pingRef.current) clearInterval(pingRef.current);
    pingRef.current = setInterval(async () => {
      try { await fetch(`${GATEWAY_URL}/api/notebook-sessions/ping`, { method: "POST", headers: await getAuthHeaders() }); } catch {}
    }, 60000);
  }

  function resetForm() {
    setForm({ name: "", display_name: "", description: "", connection_name: "", git_remote: "" });
    setSource("managed");
    setShowCreate(false);
  }

  async function handleCreate() {
    if (!form.name || !NAME_PATTERN.test(form.name)) { toast("name must match [a-zA-Z0-9_-]", "error"); return; }
    if (!form.display_name) { toast("display name is required", "error"); return; }
    if (source === "github" && !form.git_remote) { toast("github repo url is required", "error"); return; }
    setCreating(true);
    try {
      const p = await createWorkspaceProject({
        name: form.name, display_name: form.display_name, description: form.description || undefined,
        source, connection_name: form.connection_name || undefined, git_remote: form.git_remote || undefined,
      });
      setProjects((prev) => [p, ...prev]);
      resetForm();
    } catch (e) { toast(String(e), "error"); }
    finally { setCreating(false); }
  }

  const [iframeLoaded, setIframeLoaded] = useState(false);

  // Full-screen IDE mode
  if ((ideStatus === "running" || ideStatus === "starting") && (ideUrl || ideStatus === "starting")) {
    return (
      <div className="flex flex-col h-screen">
        <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
          <div className="flex items-center gap-3">
            <Code className="w-4 h-4 text-[var(--color-text)]" />
            <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-text)]">
              SignalPilot IDE
            </span>
            {ideStatus === "starting" ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--color-text-dim)]" />
                <span className="text-[11px] text-[var(--color-text-dim)]">starting...</span>
              </>
            ) : !iframeLoaded ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--color-text-dim)]" />
                <span className="text-[11px] text-[var(--color-text-dim)]">loading...</span>
              </>
            ) : (
              <>
                <StatusDot status="healthy" size={4} pulse />
                <span className="text-[11px] text-[var(--color-success)]">running</span>
              </>
            )}
          </div>
          <button
            onClick={() => { stopIde(); setIframeLoaded(false); }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
          >
            <Square className="w-3 h-3" /> stop
          </button>
        </div>
        <div className="flex-1 relative">
          {(!ideUrl || !iframeLoaded) && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-[var(--color-bg)] z-10">
              <Loader2 className="w-8 h-8 animate-spin text-[var(--color-text-dim)]" />
              <span className="text-xs text-[var(--color-text-dim)] tracking-wider uppercase">
                {ideStatus === "starting" ? "starting notebook pod..." : "loading IDE..."}
              </span>
            </div>
          )}
          {ideUrl && (
            <iframe
              src={ideUrl}
              className="absolute inset-0 w-full h-full border-0"
              style={{ opacity: iframeLoaded ? 1 : 0, transition: "opacity 300ms ease-in" }}
              onLoad={() => setIframeLoaded(true)}
              allow="clipboard-read; clipboard-write"
            />
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 animate-fade-in">
      <PageHeader
        title="projects"
        subtitle="workspace"
        description="branch-based project management"
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={launchIde}
              disabled={ideStatus === "starting"}
              className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
            >
              {ideStatus === "starting" ? (
                <><Loader2 className="w-3.5 h-3.5 animate-spin" /> starting IDE...</>
              ) : (
                <><Code className="w-3.5 h-3.5" /> open IDE</>
              )}
            </button>
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
            >
              <Plus className="w-3.5 h-3.5" /> new project
            </button>
          </div>
        }
      />

      <TerminalBar
        path="workspace-projects --list"
        status={<StatusDot status={projects.length > 0 ? "healthy" : "unknown"} size={4} pulse={false} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">total: <code className="text-[12px] text-[var(--color-text)]">{projects.length}</code></span>
          <span className="text-[var(--color-text-dim)]">active: <code className="text-[12px] text-[var(--color-success)]">{projects.filter(p => p.status === "active").length}</code></span>
        </div>
      </TerminalBar>

      {showCreate && (
        <div className="mb-6 border border-[var(--color-border)] bg-[var(--color-bg-card)] animate-scale-in overflow-hidden">
          <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center gap-2">
            <FolderOpen className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">new project</span>
          </div>
          <div className="p-5">
            <div className="flex items-center gap-2 mb-5">
              {(Object.keys(SOURCE_LABELS) as Source[]).map((s) => {
                const { label, icon: Icon } = SOURCE_LABELS[s];
                return (
                  <button
                    key={s}
                    onClick={() => setSource(s)}
                    className={`flex items-center gap-2 px-4 py-2.5 text-xs tracking-wider border transition-all ${
                      source === s
                        ? "border-[var(--color-text)] text-[var(--color-text)] bg-[var(--color-bg-input)]"
                        : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5" strokeWidth={1.5} />
                    <span className="uppercase">{label}</span>
                  </button>
                );
              })}
            </div>
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">name (slug)</label>
                <input type="text" placeholder="my-project" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide" />
              </div>
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">display name</label>
                <input type="text" placeholder="My Project" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide" />
              </div>
            </div>
            {source === "github" && (
              <div className="mb-4">
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">github repo url</label>
                <input type="text" placeholder="https://github.com/org/repo.git" value={form.git_remote} onChange={(e) => setForm({ ...form, git_remote: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide font-mono" />
              </div>
            )}
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">description</label>
                <input type="text" placeholder="optional" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide" />
              </div>
              <div>
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">connection (optional)</label>
                <select value={form.connection_name} onChange={(e) => setForm({ ...form, connection_name: e.target.value })}
                  className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]">
                  <option value="">none</option>
                  {connections.map((c) => (<option key={c.name} value={c.name}>{c.name} ({c.db_type})</option>))}
                </select>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button onClick={handleCreate} disabled={creating}
                className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30">
                {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                {source === "managed" ? "create" : source === "github" ? "import" : "connect"}
              </button>
              <button onClick={resetForm} className="px-4 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider">cancel</button>
            </div>
          </div>
        </div>
      )}

      {projects.length === 0 ? (
        <EmptyState
          icon={EmptyProject}
          title="no projects"
          description="create a workspace project to get started"
          action={
            <button onClick={() => setShowCreate(true)}
              className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider">
              <Plus className="w-3.5 h-3.5" /> create first project
            </button>
          }
        />
      ) : (
        <div className="grid grid-cols-3 gap-px bg-[var(--color-border)] stagger-fade-in">
          {projects.map((proj) => (
            <Link key={proj.id} href={`/projects/${proj.id}`}
              className="group block bg-[var(--color-bg-card)] hover:bg-[var(--color-bg-hover)] transition-all card-accent-top overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
                <div className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: proj.status === "active" ? "var(--color-success)" : "var(--color-text-dim)", opacity: proj.status === "active" ? 1 : 0.4 }} />
                  <span className="w-2 h-2 rounded-full bg-[var(--color-text-dim)] opacity-20" />
                  <span className="w-2 h-2 rounded-full bg-[var(--color-text-dim)] opacity-10" />
                </div>
                <div className="flex items-center gap-2">
                  <span className="px-1.5 py-0.5 border border-[var(--color-border)] text-[10px] tracking-wider uppercase">{proj.source}</span>
                  <span className="text-[11px] text-[var(--color-text-dim)] tracking-[0.15em] uppercase">{proj.status}</span>
                </div>
                <ArrowRight className="w-3 h-3 text-[var(--color-text-dim)] opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
              <div className="p-4 space-y-2.5">
                <div className="flex items-center gap-2">
                  {sourceIcon(proj.source)}
                  <span className="text-xs text-[var(--color-text)] font-bold uppercase tracking-wider group-hover:text-white transition-colors">{proj.display_name}</span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-[12px] text-[var(--color-text-dim)] tracking-wider">
                  {proj.connection_name && (<div className="flex items-center gap-1.5"><Database className="w-3 h-3" strokeWidth={1.5} /><span className="truncate">{proj.connection_name}</span></div>)}
                  <div className="flex items-center gap-1.5 tabular-nums"><FileText className="w-3 h-3" strokeWidth={1.5} /><span>{proj.file_count} files</span></div>
                  <div className="flex items-center gap-1.5 tabular-nums"><HardDrive className="w-3 h-3" strokeWidth={1.5} /><span>{formatBytes(proj.total_bytes)}</span></div>
                  <div className="flex items-center gap-1.5"><Clock className="w-3 h-3" strokeWidth={1.5} /><TimeAgo timestamp={proj.updated_at} live className="tabular-nums" /></div>
                </div>
                {proj.tags && proj.tags.length > 0 && (
                  <div className="flex items-center gap-2 pt-1">
                    {proj.tags.map((tag) => (<span key={tag} className="px-1.5 py-0.5 border border-[var(--color-border)] text-[11px] tracking-wider">{tag}</span>))}
                  </div>
                )}
                {proj.description && <p className="text-[11px] text-[var(--color-text-dim)] truncate">{proj.description}</p>}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

async function getAuthHeaders(): Promise<Record<string, string>> {
  const h: Record<string, string> = {};
  const key = typeof window !== "undefined" ? sessionStorage.getItem("sp_api_key") : null;
  if (key) h["Authorization"] = `Bearer ${key}`;
  return h;
}
