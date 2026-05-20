"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Trash2,
  Loader2,
  Database,
  Clock,
  FolderOpen,
  FileText,
  HardDrive,
  ArrowLeft,
  Play,
  Square,
  File,
  X,
  GitBranch,
} from "lucide-react";
import {
  getWorkspaceProject,
  deleteWorkspaceProject,
  getWorkspaceFiles,
  deleteWorkspaceFile,
  getWorkspaceBranches,
  getUserSession,
  createNotebookSession,
  getNotebookSession,
  deleteNotebookSession,
  pingNotebookSession,
} from "@/lib/api";
import type { WorkspaceProjectInfo, WorkspaceFileInfo } from "@/lib/types";
import { PageHeader } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";
import { DestructiveConfirmDialog } from "@/components/ui/destructive-confirm";
import { TimeAgo } from "@/components/ui/time-ago";
import Link from "next/link";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function fileIcon(key: string) {
  if (key.endsWith(".sql")) return <span className="text-[10px] font-mono text-blue-400">SQL</span>;
  if (key.endsWith(".yml") || key.endsWith(".yaml")) return <span className="text-[10px] font-mono text-yellow-400">YML</span>;
  if (key.endsWith(".py")) return <span className="text-[10px] font-mono text-green-400">PY</span>;
  if (key.endsWith(".md")) return <span className="text-[10px] font-mono text-gray-400">MD</span>;
  return <File className="w-3 h-3 text-[var(--color-text-dim)]" />;
}

export default function ProjectDetailPage() {
  const { toast } = useToast();
  const router = useRouter();
  const params = useParams();
  const projectId = params.id as string;

  const [project, setProject] = useState<WorkspaceProjectInfo | null>(null);
  const [files, setFiles] = useState<WorkspaceFileInfo[]>([]);
  const [activeBranch, setActiveBranch] = useState("main");
  const [showDelete, setShowDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Build-time gateway origin — used to construct the /_init iframe URL.
  // NEXT_PUBLIC_GATEWAY_URL is substituted at build time by Next.js; it must
  // not be derived from any runtime API response (prevents URL injection).
  const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3300";

  // Notebook session state
  const [notebookStatus, setNotebookStatus] = useState<"idle" | "starting" | "running" | "error">("idle");
  const [notebookProxy, setNotebookProxy] = useState<string | null>(null);
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(() => {
    getWorkspaceProject(projectId).then(setProject).catch(() => {});
    getUserSession(projectId).then((s) => {
      setActiveBranch(s.active_branch);
      getWorkspaceFiles(projectId, s.active_branch).then((res) => setFiles(res.files)).catch(() => {});
    }).catch(() => {
      getWorkspaceFiles(projectId, "main").then((res) => setFiles(res.files)).catch(() => {});
    });
  }, [projectId]);

  // Check for existing notebook session on load
  useEffect(() => {
    refresh();
    checkNotebookSession();
  }, [refresh]);

  // Cleanup ping on unmount
  useEffect(() => {
    return () => {
      if (pingRef.current) clearInterval(pingRef.current);
    };
  }, []);

  async function checkNotebookSession() {
    try {
      const session = await getNotebookSession();
      if (session && session.status === "running" && session.notebook_url) {
        setNotebookStatus("running");
        // notebook_url is a relative path (/notebook/{id}/_init); prepend
        // the gateway origin so the browser navigates to the proxy endpoint
        // that sets the HttpOnly cookie and 302s into marimo. The marimo
        // access token never appears in any frontend URL or DOM.
        setNotebookProxy(`${GATEWAY_URL}${session.notebook_url}`);
        startPing();
      }
    } catch {}
  }

  async function launchNotebook() {
    setNotebookStatus("starting");
    try {
      const session = await createNotebookSession({ project_id: projectId, branch: activeBranch });
      if (!session.notebook_url) {
        toast("Session created but notebook URL not available", "error");
        setNotebookStatus("error");
        return;
      }
      setNotebookStatus("running");
      setNotebookProxy(`${GATEWAY_URL}${session.notebook_url}`);
      startPing();
    } catch (e) {
      toast(String(e), "error");
      setNotebookStatus("error");
    }
  }

  async function stopNotebook() {
    try {
      await deleteNotebookSession();
    } catch {}
    setNotebookStatus("idle");
    setNotebookProxy(null);
    if (pingRef.current) {
      clearInterval(pingRef.current);
      pingRef.current = null;
    }
  }

  function startPing() {
    if (pingRef.current) clearInterval(pingRef.current);
    pingRef.current = setInterval(async () => {
      try {
        await pingNotebookSession();
      } catch {}
    }, 60000);
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await stopNotebook();
      await deleteWorkspaceProject(projectId);
      router.push("/projects");
    } catch (e) { toast(String(e), "error"); setDeleting(false); }
  }

  async function handleDeleteFile(key: string) {
    try {
      await deleteWorkspaceFile(projectId, activeBranch, key);
      setFiles((prev) => prev.filter((f) => f.key !== key));
      toast(`deleted ${key}`, "success");
    } catch (e) { toast(String(e), "error"); }
  }

  if (!project) {
    return (
      <div className="p-8 animate-fade-in">
        <div className="flex items-center gap-2 text-xs text-[var(--color-text-dim)]">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> loading project...
        </div>
      </div>
    );
  }

  // When notebook is running, show it full-screen with a thin header
  if (notebookStatus === "running" && notebookProxy) {
    return (
      <div className="flex flex-col h-screen">
        <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
          <div className="flex items-center gap-3">
            <Link
              href="/projects"
              className="text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
            </Link>
            <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-text)]">
              {project.display_name}
            </span>
            <div className="flex items-center gap-1.5">
              <GitBranch className="w-3 h-3 text-[var(--color-text-dim)]" />
              <span className="text-[11px] text-[var(--color-text-dim)]">{activeBranch}</span>
            </div>
            <StatusDot status="healthy" size={4} pulse />
            <span className="text-[11px] text-[var(--color-success)]">running</span>
          </div>
          <button
            onClick={stopNotebook}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
          >
            <Square className="w-3 h-3" /> stop
          </button>
        </div>
        {/*
          sandbox rationale: allow-scripts + allow-same-origin together
          effectively negates the sandboxing isolation for same-origin documents
          — this is intentional. Marimo requires both: allow-scripts for kernel
          execution, allow-same-origin for its own localStorage/IndexedDB access.
          This sandbox attribute is defense-in-depth (no allow-popups, no
          allow-top-navigation), not a primary isolation mechanism. Primary
          isolation is the gateway proxy auth layer (sp_nb_* HttpOnly cookie +
          ownership check on every request).
        */}
        <iframe
          src={notebookProxy}
          title="Marimo notebook"
          className="flex-1 w-full border-0"
          allow="clipboard-read; clipboard-write"
          sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
        />
      </div>
    );
  }

  return (
    <div className="p-8 animate-fade-in">
      <Link
        href="/projects"
        className="inline-flex items-center gap-1.5 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider mb-4"
      >
        <ArrowLeft className="w-3 h-3" /> projects
      </Link>

      <PageHeader
        title={project.display_name}
        subtitle="workspace"
        description={project.description || project.name}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={launchNotebook}
              disabled={notebookStatus === "starting"}
              className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
            >
              {notebookStatus === "starting" ? (
                <><Loader2 className="w-3.5 h-3.5 animate-spin" /> starting...</>
              ) : (
                <><Play className="w-3.5 h-3.5" /> launch notebook</>
              )}
            </button>
            <button
              onClick={() => setShowDelete(true)}
              className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
            >
              <Trash2 className="w-3.5 h-3.5" /> delete
            </button>
          </div>
        }
      />

      {notebookStatus === "error" && (
        <div className="mb-4 px-4 py-3 border border-[var(--color-error)] bg-[var(--color-error)]/10 text-xs text-[var(--color-error)]">
          Failed to start notebook. Check that K3s is running and the notebook image is built.
        </div>
      )}

      <div className="flex items-center gap-3 mb-6">
        <StatusDot status={project.status === "active" ? "healthy" : "warning"} size={6} pulse={false} />
        <span className="text-xs text-[var(--color-text-muted)] uppercase tracking-wider">{project.status}</span>
        <span className="px-1.5 py-0.5 border border-[var(--color-border)] text-[11px] tracking-wider">{project.source}</span>
        {project.connection_name && (
          <span className="px-1.5 py-0.5 border border-[var(--color-border)] text-[11px] tracking-wider">{project.connection_name}</span>
        )}
        <div className="flex items-center gap-1.5">
          <GitBranch className="w-3 h-3 text-[var(--color-text-dim)]" />
          <span className="text-[11px] text-[var(--color-text-dim)]">{activeBranch}</span>
        </div>
      </div>

      {/* Project info */}
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden mb-6">
        <div className="px-5 py-3 border-b border-[var(--color-border)]">
          <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">project details</span>
        </div>
        <div className="p-5 space-y-3">
          <InfoRow icon={<FolderOpen className="w-3.5 h-3.5" strokeWidth={1.5} />} label="slug" value={project.name} mono />
          {project.connection_name && (
            <InfoRow icon={<Database className="w-3.5 h-3.5" strokeWidth={1.5} />} label="connection" value={project.connection_name} />
          )}
          <InfoRow icon={<HardDrive className="w-3.5 h-3.5" strokeWidth={1.5} />} label="s3 prefix" value={project.s3_prefix} mono />
          <InfoRow icon={<FileText className="w-3.5 h-3.5" strokeWidth={1.5} />} label="files" value={`${project.file_count} files (${formatBytes(project.total_bytes)})`} />
          <InfoRow icon={<Clock className="w-3.5 h-3.5" strokeWidth={1.5} />} label="created" value={<TimeAgo timestamp={project.created_at} live className="tabular-nums" />} />
          <InfoRow icon={<Clock className="w-3.5 h-3.5" strokeWidth={1.5} />} label="updated" value={<TimeAgo timestamp={project.updated_at} live className="tabular-nums" />} />
        </div>
      </div>

      {/* File browser */}
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
        <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
          <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">files ({activeBranch})</span>
          <span className="text-[11px] text-[var(--color-text-dim)] tabular-nums">{files.length} files</span>
        </div>
        {files.length === 0 ? (
          <div className="p-8 text-center text-xs text-[var(--color-text-dim)]">
            no files yet — launch the notebook to start editing
          </div>
        ) : (
          <div className="divide-y divide-[var(--color-border)]">
            {files.map((file) => (
              <div key={file.key} className="flex items-center gap-3 px-5 py-2.5 hover:bg-[var(--color-bg-hover)] transition-colors group">
                <span className="w-6 flex-shrink-0 flex items-center justify-center">{fileIcon(file.key)}</span>
                <span className="flex-1 text-xs font-mono text-[var(--color-text)] truncate">{file.key}</span>
                <span className="text-[11px] text-[var(--color-text-dim)] tabular-nums">{formatBytes(file.size)}</span>
                <TimeAgo timestamp={file.last_modified} live className="text-[11px] text-[var(--color-text-dim)] tabular-nums" />
                <button
                  onClick={() => handleDeleteFile(file.key)}
                  className="opacity-0 group-hover:opacity-100 p-0.5 text-[var(--color-text-dim)] hover:text-[var(--color-error)] transition-all"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <DestructiveConfirmDialog
        open={showDelete}
        projectName={project.display_name}
        onConfirm={handleDelete}
        onCancel={() => setShowDelete(false)}
        confirming={deleting}
      />
    </div>
  );
}

function InfoRow({ icon, label, value, mono = false }: { icon: React.ReactNode; label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="text-[var(--color-text-dim)]">{icon}</span>
      <span className="text-[var(--color-text-dim)] tracking-wider w-28">{label}</span>
      <span className={`text-[var(--color-text)] ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}

