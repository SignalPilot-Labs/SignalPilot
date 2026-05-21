"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  Loader2,
  Code,
  ExternalLink,
  Square,
  Share2,
  Check,
} from "lucide-react";
import {
  createNotebookSession,
  getNotebookSession,
  deleteNotebookSession,
  pingNotebookSession,
} from "@/lib/api";
import { StatusDot } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";

export default function ProjectsPage() {
  const { toast } = useToast();
  const searchParams = useSearchParams();
  const router = useRouter();

  const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3300";

  const [ideStatus, setIdeStatus] = useState<"closed" | "starting" | "running">("closed");
  const [ideUrl, setIdeUrl] = useState<string | null>(null);
  const [iframeLoaded, setIframeLoaded] = useState(false);
  const [copied, setCopied] = useState(false);
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Read deep-link params from URL
  const urlProject = searchParams.get("project") || "";
  const urlBranch = searchParams.get("branch") || "";
  const urlFile = searchParams.get("file") || "";

  // Track current notebook context (updated via postMessage from iframe)
  const [currentProject, setCurrentProject] = useState(urlProject);
  const [currentBranch, setCurrentBranch] = useState(urlBranch);
  const [currentFile, setCurrentFile] = useState(urlFile);

  function buildIdeUrl(sessionUrl: string) {
    let url = `${GATEWAY_URL}${sessionUrl}`;
    const params = new URLSearchParams();
    if (currentProject || urlProject) params.set("project", currentProject || urlProject);
    if (currentBranch || urlBranch) params.set("branch", currentBranch || urlBranch);
    if (currentFile || urlFile) params.set("file", currentFile || urlFile);
    const qs = params.toString();
    if (qs) url += (url.includes("?") ? "&" : "?") + qs;
    return url;
  }

  // Listen for postMessage from iframe (notebook navigation events)
  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== new URL(GATEWAY_URL).origin) return;
      const data = event.data;
      if (data?.type === "sp:navigation") {
        if (data.project) setCurrentProject(data.project);
        if (data.branch) setCurrentBranch(data.branch);
        if (data.file) setCurrentFile(data.file);
      }
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [GATEWAY_URL]);

  useEffect(() => {
    checkSession();
    // Auto-launch if deep-link params present
    if (urlProject && ideStatus === "closed") {
      launchIde();
    }
    return () => { if (pingRef.current) clearInterval(pingRef.current); };
  }, []);

  async function checkSession() {
    try {
      const session = await getNotebookSession();
      if (session && session.status === "running" && session.notebook_url) {
        setIdeStatus("running");
        setIdeUrl(buildIdeUrl(session.notebook_url));
        startPing();
      }
    } catch {}
  }

  async function launchIde() {
    setIdeStatus("starting");
    setIframeLoaded(false);
    try {
      const session = await createNotebookSession({ project_id: urlProject || "", branch: urlBranch || "main" });
      if (!session.notebook_url) {
        toast("Session created but notebook URL not available", "error");
        setIdeStatus("closed");
        return;
      }
      setIdeStatus("running");
      setIdeUrl(buildIdeUrl(session.notebook_url));
      startPing();
    } catch (e) {
      toast(String(e), "error");
      setIdeStatus("closed");
    }
  }

  async function launchExternal() {
    setIdeStatus("starting");
    try {
      const session = await createNotebookSession({ project_id: urlProject || "", branch: urlBranch || "main" });
      if (session.notebook_url) {
        window.open(buildIdeUrl(session.notebook_url), "_blank");
      }
      setIdeStatus("closed");
    } catch (e) {
      toast(String(e), "error");
      setIdeStatus("closed");
    }
  }

  async function stopIde() {
    try { await deleteNotebookSession(); } catch {}
    setIdeStatus("closed");
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

  function getShareUrl() {
    const base = window.location.origin + "/projects";
    const params = new URLSearchParams();
    if (currentProject) params.set("project", currentProject);
    if (currentBranch) params.set("branch", currentBranch);
    if (currentFile) params.set("file", currentFile);
    const qs = params.toString();
    return qs ? `${base}?${qs}` : base;
  }

  async function handleShare() {
    const url = getShareUrl();
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      toast("Link copied to clipboard", "success");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast(url, "success");
    }
  }

  // Full-screen IDE mode
  if (ideStatus !== "closed" && (ideUrl || ideStatus === "starting")) {
    return (
      <div className="flex flex-col h-screen">
        <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
          <div className="flex items-center gap-3">
            <Code className="w-4 h-4 text-[var(--color-text)]" />
            <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-text)]">
              SignalPilot IDE
            </span>
            {!iframeLoaded ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--color-text-dim)]" />
                <span className="text-[11px] text-[var(--color-text-dim)]">
                  {!ideUrl ? "starting..." : "loading..."}
                </span>
              </>
            ) : (
              <>
                <StatusDot status="healthy" size={4} pulse />
                <span className="text-[11px] text-[var(--color-success)]">running</span>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleShare}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
            >
              {copied ? <Check className="w-3 h-3" /> : <Share2 className="w-3 h-3" />}
              {copied ? "copied" : "share"}
            </button>
            {ideUrl && (
              <a
                href={ideUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
              >
                <ExternalLink className="w-3 h-3" /> external
              </a>
            )}
            <button
              onClick={() => { stopIde(); setIframeLoaded(false); }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
            >
              <Square className="w-3 h-3" /> stop
            </button>
          </div>
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
              ref={iframeRef}
              src={ideUrl}
              title="Marimo notebook"
              className="absolute inset-0 w-full h-full border-0"
              style={{ opacity: iframeLoaded ? 1 : 0, transition: "opacity 300ms ease-in" }}
              onLoad={() => setIframeLoaded(true)}
              allow="clipboard-read; clipboard-write"
              sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
            />
          )}
        </div>
      </div>
    );
  }

  // Landing — two buttons
  return (
    <div className="p-8 animate-fade-in">
      <div className="max-w-md mx-auto mt-24">
        <div className="flex items-center gap-3 mb-8">
          <Code className="w-6 h-6 text-[var(--color-text)]" />
          <h1 className="text-lg font-bold uppercase tracking-wider text-[var(--color-text)]">
            SignalPilot IDE
          </h1>
        </div>

        <div className="space-y-3">
          <button
            onClick={launchIde}
            className="w-full flex items-center gap-3 px-5 py-4 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90"
          >
            <Code className="w-4 h-4" />
            <span>open IDE</span>
          </button>

          <button
            onClick={launchExternal}
            className="w-full flex items-center gap-3 px-5 py-4 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
          >
            <ExternalLink className="w-4 h-4" />
            <span>open in new tab</span>
          </button>
        </div>
      </div>
    </div>
  );
}
