"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Loader2,
  ArrowLeft,
  Square,
  Code,
  ExternalLink,
  GitBranch,
  Trash2,
} from "lucide-react";
import {
  getWorkspaceProject,
  deleteWorkspaceProject,
  createNotebookSession,
  getNotebookSession,
  deleteNotebookSession,
  pingNotebookSession,
} from "@/lib/api";
import type { WorkspaceProjectInfo } from "@/lib/types";
import { StatusDot } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";
import { DestructiveConfirmDialog } from "@/components/ui/destructive-confirm";
import Link from "next/link";

export default function ProjectDetailPage() {
  const { toast } = useToast();
  const router = useRouter();
  const params = useParams();
  const projectId = params.id as string;

  const [project, setProject] = useState<WorkspaceProjectInfo | null>(null);
  const [showDelete, setShowDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3300";

  const [ideStatus, setIdeStatus] = useState<"idle" | "starting" | "running" | "error">("idle");
  const [ideUrl, setIdeUrl] = useState<string | null>(null);
  const [iframeLoaded, setIframeLoaded] = useState(false);
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    getWorkspaceProject(projectId).then(setProject).catch(() => {});
    checkSession();
    return () => { if (pingRef.current) clearInterval(pingRef.current); };
  }, [projectId]);

  async function checkSession() {
    try {
      const session = await getNotebookSession();
      if (session && session.status === "running" && session.notebook_url) {
        setIdeStatus("running");
        setIdeUrl(`${GATEWAY_URL}${session.notebook_url}`);
        startPing();
      }
    } catch {}
  }

  async function launchIde() {
    setIdeStatus("starting");
    setIframeLoaded(false);
    try {
      const session = await createNotebookSession({ project_id: projectId, branch: "main" });
      if (!session.notebook_url) {
        toast("Session created but notebook URL not available", "error");
        setIdeStatus("error");
        return;
      }
      setIdeStatus("running");
      const params = new URLSearchParams();
      params.set("project", projectId);
      params.set("branch", "main");
      params.set("file", "__new__project");
      setIdeUrl(`${GATEWAY_URL}${session.notebook_url}?${params.toString()}`);
      startPing();
    } catch (e) {
      toast(String(e), "error");
      setIdeStatus("error");
    }
  }

  async function stopIde() {
    try { await deleteNotebookSession(); } catch {}
    setIdeStatus("idle");
    setIdeUrl(null);
    setIframeLoaded(false);
    if (pingRef.current) { clearInterval(pingRef.current); pingRef.current = null; }
  }

  function startPing() {
    if (pingRef.current) clearInterval(pingRef.current);
    pingRef.current = setInterval(async () => {
      try { await pingNotebookSession(); } catch {}
    }, 60000);
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await stopIde();
      await deleteWorkspaceProject(projectId);
      router.push("/projects");
    } catch (e) { toast(String(e), "error"); setDeleting(false); }
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

  // Full-screen inline IDE mode
  if (ideStatus === "running" && ideUrl) {
    return (
      <div className="flex flex-col h-screen">
        <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
          <div className="flex items-center gap-3">
            <button
              onClick={() => { stopIde(); }}
              className="text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
            </button>
            <Code className="w-4 h-4 text-[var(--color-text)]" />
            <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-text)]">
              {project.display_name}
            </span>
            <div className="flex items-center gap-1.5">
              <GitBranch className="w-3 h-3 text-[var(--color-text-dim)]" />
              <span className="text-[11px] text-[var(--color-text-dim)]">main</span>
            </div>
            {!iframeLoaded ? (
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
          <div className="flex items-center gap-2">
            <a
              href={ideUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
            >
              <ExternalLink className="w-3 h-3" /> open external
            </a>
            <button
              onClick={() => { stopIde(); setIframeLoaded(false); }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
            >
              <Square className="w-3 h-3" /> stop
            </button>
          </div>
        </div>
        <div className="flex-1 relative">
          {!iframeLoaded && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-[var(--color-bg)] z-10">
              <Loader2 className="w-8 h-8 animate-spin text-[var(--color-text-dim)]" />
              <span className="text-xs text-[var(--color-text-dim)] tracking-wider uppercase">loading IDE...</span>
            </div>
          )}
          <iframe
            src={ideUrl}
            title="Marimo notebook"
            className="absolute inset-0 w-full h-full border-0"
            style={{ opacity: iframeLoaded ? 1 : 0, transition: "opacity 300ms ease-in" }}
            onLoad={() => setIframeLoaded(true)}
            allow="clipboard-read; clipboard-write"
            sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
          />
        </div>
      </div>
    );
  }

  // Project landing — two launch options + delete
  return (
    <div className="p-8 animate-fade-in">
      <Link
        href="/projects"
        className="inline-flex items-center gap-1.5 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider mb-6"
      >
        <ArrowLeft className="w-3 h-3" /> projects
      </Link>

      <div className="max-w-lg mx-auto mt-16">
        <div className="flex items-center gap-3 mb-2">
          <Code className="w-5 h-5 text-[var(--color-text)]" />
          <h1 className="text-lg font-bold uppercase tracking-wider text-[var(--color-text)]">
            {project.display_name}
          </h1>
        </div>
        {project.description && (
          <p className="text-xs text-[var(--color-text-dim)] mb-8 ml-8">{project.description}</p>
        )}

        <div className="space-y-3 ml-8">
          <button
            onClick={launchIde}
            disabled={ideStatus === "starting"}
            className="w-full flex items-center gap-3 px-5 py-4 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
          >
            {ideStatus === "starting" ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Code className="w-4 h-4" />
            )}
            <span>{ideStatus === "starting" ? "starting notebook..." : "open IDE"}</span>
          </button>

          <button
            onClick={async () => {
              setIdeStatus("starting");
              try {
                const session = await createNotebookSession({ project_id: projectId, branch: "main" });
                if (session.notebook_url) {
                  window.open(`${GATEWAY_URL}${session.notebook_url}`, "_blank");
                  setIdeStatus("idle");
                }
              } catch (e) {
                toast(String(e), "error");
                setIdeStatus("idle");
              }
            }}
            disabled={ideStatus === "starting"}
            className="w-full flex items-center gap-3 px-5 py-4 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase disabled:opacity-30"
          >
            <ExternalLink className="w-4 h-4" />
            <span>open in new tab</span>
          </button>
        </div>

        {ideStatus === "error" && (
          <div className="mt-4 ml-8 px-4 py-3 border border-[var(--color-error)] bg-[var(--color-error)]/10 text-xs text-[var(--color-error)]">
            Failed to start notebook. Check that K3s is running and the notebook image is built.
          </div>
        )}

        <div className="mt-12 ml-8 pt-6 border-t border-[var(--color-border)]">
          <button
            onClick={() => setShowDelete(true)}
            className="flex items-center gap-2 text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-error)] transition-colors tracking-wider uppercase"
          >
            <Trash2 className="w-3 h-3" /> delete project
          </button>
        </div>
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
