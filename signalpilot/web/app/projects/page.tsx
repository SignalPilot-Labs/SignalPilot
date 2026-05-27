"use client";

import { useEffect, useState, useRef } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
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
} from "~/lib/api";
import { StatusDot } from "~/components/ui/data-viz";
import { useToast } from "~/components/ui/toast";
import {
  NotebookProvider,
  type NotebookConfig,
} from "~/components/notebook/notebook-context";

const NotebookBoot = dynamic(
  () => import("~/components/notebook/notebook-boot"),
  {
    ssr: false,
    loading: () => (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-[var(--color-text-dim)]" />
      </div>
    ),
  }
);

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3300";

type AppState = "loading" | "no-session" | "ready";

function IDEHeader({
  children,
  right,
}: {
  children?: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
      <div className="flex items-center gap-3">
        <Code className="w-4 h-4 text-[var(--color-text)]" />
        <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-text)]">
          SignalPilot IDE
        </span>
        {children}
      </div>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </div>
  );
}

export default function ProjectsPage() {
  const { toast } = useToast();
  const searchParams = useSearchParams();

  const urlProject = searchParams.get("project") || "";
  const urlBranch = searchParams.get("branch") || "";
  const rawFile = searchParams.get("file") || "";
  const urlFile = rawFile === "__new__project" ? "" : rawFile;
  const hasDeepLink = Boolean(urlProject);

  const [state, setState] = useState<AppState>("loading");
  const [launchStatus, setLaunchStatus] = useState(hasDeepLink ? "connecting to pod..." : "");
  const [notebookConfig, setNotebookConfig] = useState<NotebookConfig | null>(null);
  const [copied, setCopied] = useState(false);
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function extractToken(notebookUrl: string): string | null {
    const match = notebookUrl.match(/[?&]token=([^&]+)/);
    return match ? match[1] : null;
  }

  function buildConfig(sessionId: string, notebookUrl: string, apiKey?: string): NotebookConfig | null {
    const token = extractToken(notebookUrl);
    if (!token) return null;
    return {
      gatewayUrl: GATEWAY_URL,
      sessionId,
      token,
      apiKey,
      project: urlProject || undefined,
      branch: urlBranch || undefined,
      file: urlFile || undefined,
    };
  }

  useEffect(() => {
    let cancelled = false;

    async function init() {
      let apiKey: string | undefined;
      try {
        const keyResp = await fetch("/api/local-key");
        const keyData = (await keyResp.json()) as { key?: string };
        if (keyData?.key) apiKey = keyData.key;
      } catch (err) {
        console.warn("Failed to fetch API key:", err);
      }

      try {
        const session = await getNotebookSession();
        if (!cancelled && session?.status === "running" && session.id && session.notebook_url) {
          const config = buildConfig(session.id, session.notebook_url, apiKey);
          if (config) {
            setNotebookConfig(config);
            setState("ready");
            startPing();
            return;
          }
        }
      } catch (err) {
        console.warn("Failed to check existing session:", err);
      }

      if (!cancelled && hasDeepLink) {
        await launch(apiKey);
      } else if (!cancelled) {
        setState("no-session");
      }
    }

    init();
    return () => {
      cancelled = true;
      if (pingRef.current) clearInterval(pingRef.current);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (notebookConfig && state === "ready") {
      const newProject = urlProject || undefined;
      const newBranch = urlBranch || undefined;
      const newFile = urlFile || undefined;
      if (
        newProject !== notebookConfig.project ||
        newBranch !== notebookConfig.branch ||
        newFile !== notebookConfig.file
      ) {
        setNotebookConfig((prev) =>
          prev ? { ...prev, project: newProject, branch: newBranch, file: newFile } : prev,
        );
      }
    }
  }, [urlProject, urlBranch, urlFile, state]); // eslint-disable-line react-hooks/exhaustive-deps

  async function launch(existingApiKey?: string) {
    setState("loading");
    setLaunchStatus("creating session...");
    try {
      let apiKey = existingApiKey;
      if (!apiKey) {
        try {
          const keyResp = await fetch("/api/local-key");
          const keyData = (await keyResp.json()) as { key?: string };
          if (keyData?.key) apiKey = keyData.key;
        } catch (err) {
          console.warn("Failed to fetch API key:", err);
        }
      }

      const session = await createNotebookSession({
        project_id: urlProject || "",
        branch: urlBranch || "main",
      });
      if (!session.id) {
        toast("Session created but no ID returned", "error");
        setState("no-session");
        return;
      }
      setLaunchStatus("waiting for pod...");
      const full = await getNotebookSession();
      const notebookUrl = full?.notebook_url ?? session.notebook_url ?? "";

      const config = buildConfig(session.id, notebookUrl, apiKey);
      if (!config) {
        toast("No session token in notebook URL", "error");
        setState("no-session");
        return;
      }

      setNotebookConfig(config);
      setState("ready");
      startPing();
    } catch (e) {
      toast(String(e), "error");
      setState("no-session");
    }
  }

  async function stop() {
    try {
      await deleteNotebookSession();
    } catch (err) {
      console.warn("Failed to delete session:", err);
    }
    setState("no-session");
    setNotebookConfig(null);
    if (pingRef.current) { clearInterval(pingRef.current); pingRef.current = null; }
  }

  function startPing() {
    if (pingRef.current) clearInterval(pingRef.current);
    pingRef.current = setInterval(() => {
      pingNotebookSession().catch((err) => console.warn("Ping failed:", err));
    }, 60_000);
  }

  async function handleShare() {
    const url = window.location.href;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      toast("Link copied to clipboard", "success");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast(url, "success");
    }
  }

  // ─── Render: Loading ──────────────────────────────────────────
  if (state === "loading") {
    return (
      <div className="flex flex-col h-screen">
        <IDEHeader>
          <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--color-text-dim)]" />
          <span className="text-[11px] text-[var(--color-text-dim)]">{launchStatus}</span>
        </IDEHeader>
        <div className="flex-1 flex flex-col items-center justify-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-[var(--color-text-dim)]" />
          <span className="text-xs text-[var(--color-text-dim)] tracking-wider uppercase">
            {launchStatus}
          </span>
        </div>
      </div>
    );
  }

  // ─── Render: Ready ────────────────────────────────────────────
  if (state === "ready" && notebookConfig) {
    return (
      <div className="flex flex-col h-screen">
        <IDEHeader
          right={
            <>
              <button
                onClick={handleShare}
                className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
              >
                {copied ? <Check className="w-3 h-3" /> : <Share2 className="w-3 h-3" />}
                {copied ? "copied" : "share"}
              </button>
              <a
                href={`${GATEWAY_URL}/notebook/${notebookConfig.sessionId}/`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
              >
                <ExternalLink className="w-3 h-3" /> external
              </a>
              <button
                onClick={stop}
                className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
              >
                <Square className="w-3 h-3" /> stop
              </button>
            </>
          }
        >
          <StatusDot status="healthy" size={4} pulse />
          <span className="text-[11px] text-[var(--color-success)]">running</span>
        </IDEHeader>
        <div className="flex-1 min-h-0 overflow-hidden">
          <NotebookProvider value={notebookConfig}>
            <NotebookBoot />
          </NotebookProvider>
        </div>
      </div>
    );
  }

  // ─── Render: No session (landing) ─────────────────────────────
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
            onClick={() => launch()}
            className="w-full flex items-center gap-3 px-5 py-4 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90"
          >
            <Code className="w-4 h-4" />
            <span>open IDE</span>
          </button>
          <button
            onClick={async () => {
              try {
                const session = await createNotebookSession({ project_id: "", branch: "main" });
                if (session.notebook_url) window.open(`${GATEWAY_URL}${session.notebook_url}`, "_blank");
              } catch (e) { toast(String(e), "error"); }
            }}
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
