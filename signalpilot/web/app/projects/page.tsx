"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useSearchParams, usePathname } from "next/navigation";
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
  getGatewayAuthToken,
} from "~/lib/api";
import { StatusDot } from "~/components/ui/data-viz";
import { useToast } from "~/components/ui/toast";
import {
  NotebookProvider,
  type NotebookConfig,
} from "~/components/notebook/notebook-context";
import type { BootPhase } from "~/components/notebook/boot-runtime";
import { useSubscription } from "~/lib/subscription-context";
import { NotebooksProjectsPaywall } from "~/components/billing/notebooks-projects-paywall";

const PAID_TIERS = ["pro", "team", "enterprise", "unlimited"];

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
const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";

type AppState = "loading" | "no-session" | "booting" | "ready";

const BOOT_PHASE_LABELS: Record<string, string> = {
  health: "connecting to runtime...",
  syncing: "syncing project files...",
  sessions: "preparing workspace...",
  ready: "running",
};

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
  const pathname = usePathname();
  // On the full-page /notebook view we're already "external" — hide the pop-out button.
  const isExternalView = pathname?.startsWith("/notebook") ?? false;
  const { planTier, isLoaded: subLoaded } = useSubscription();

  // Projects is a paid feature. Local mode reports "team" so it's never gated.
  // In cloud mode, free-tier users see an upgrade paywall instead of the IDE.
  const isPaid = PAID_TIERS.includes(planTier);
  const gated = IS_CLOUD_MODE && subLoaded && !isPaid;

  const urlProject = searchParams.get("project") || "";
  const urlBranch = searchParams.get("branch") || "";
  const rawFile = searchParams.get("file") || "";
  const urlFile = rawFile === "__new__project" ? "" : rawFile;
  const hasDeepLink = Boolean(urlProject);

  const [state, setState] = useState<AppState>("loading");
  const [launchStatus, setLaunchStatus] = useState(hasDeepLink ? "connecting to pod..." : "");
  const [notebookConfig, setNotebookConfig] = useState<NotebookConfig | null>(null);
  const [copied, setCopied] = useState(false);
  const [bootPhase, setBootPhase] = useState<string>("health");
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleBootPhase = useCallback((phase: string) => { setBootPhase(phase); }, []);
  const handleBootReady = useCallback(() => { setState("ready"); }, []);

  function buildConfig(sessionId: string): NotebookConfig {
    // The notebook proxy authenticates the caller's Clerk JWT directly (cloud)
    // or runs without auth (local). No per-session token / cookie / handshake.
    return {
      gatewayUrl: GATEWAY_URL,
      product: "projects",
      sessionId,
      getToken: getGatewayAuthToken,
      project: urlProject || undefined,
      branch: urlBranch || undefined,
      file: urlFile || undefined,
    };
  }

  useEffect(() => {
    // Wait for the subscription to load before deciding anything in cloud mode.
    if (IS_CLOUD_MODE && !subLoaded) return;
    // Gated (free-tier cloud) users never launch a session — the paywall renders.
    if (gated) {
      setState("no-session");
      return;
    }

    let cancelled = false;

    // Show the loading state (not the "Open IDE" landing) while we check for an
    // existing session. Without this, a transient "no-session" set on an earlier
    // render can flash the landing before the session check resolves.
    setState((s) => (s === "booting" || s === "ready" ? s : "loading"));

    async function init() {
      try {
        const session = await getNotebookSession() as any;
        if (!cancelled && session?.status === "running" && session.id && session.notebook_url) {
          // If deep-linking to a specific project, verify the session matches.
          // A stale session from a different project would route to the wrong files.
          const sessionProject = session.project_id || "";
          if (urlProject && sessionProject !== urlProject) {
            console.log("[projects] Session project mismatch — deleting stale session");
            await deleteNotebookSession().catch(() => {});
          } else {
            setNotebookConfig(buildConfig(session.id));
            setState("booting");
            startPing();
            return;
          }
        }
      } catch (err) {
        console.warn("Failed to check existing session:", err);
      }

      if (!cancelled && hasDeepLink) {
        await launch();
      } else if (!cancelled) {
        setState("no-session");
      }
    }

    init();
    return () => {
      cancelled = true;
      if (pingRef.current) clearInterval(pingRef.current);
    };
  }, [subLoaded, gated]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (notebookConfig && (state === "ready" || state === "booting")) {
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

  async function launch() {
    setState("loading");
    setLaunchStatus("creating session...");
    try {
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

      setNotebookConfig(buildConfig(session.id));
      setState("booting");
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

  // ─── Render: Paywall (free-tier cloud users) ──────────────────
  if (gated) {
    return <NotebooksProjectsPaywall />;
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

  // ─── Render: Booting / Ready ──────────────────────────────────
  if ((state === "booting" || state === "ready") && notebookConfig) {
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
              {!isExternalView && (
                <a
                  href={`/notebook${(() => {
                    const p = new URLSearchParams();
                    if (urlProject) p.set("project", urlProject);
                    if (urlBranch) p.set("branch", urlBranch);
                    if (urlFile) p.set("file", urlFile);
                    const qs = p.toString();
                    return qs ? `?${qs}` : "";
                  })()}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
                >
                  <ExternalLink className="w-3 h-3" /> external
                </a>
              )}
              <button
                onClick={stop}
                className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
              >
                <Square className="w-3 h-3" /> stop
              </button>
            </>
          }
        >
          {state === "booting" ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--color-text-dim)]" />
              <span className="text-[11px] text-[var(--color-text-dim)]">
                {BOOT_PHASE_LABELS[bootPhase] || bootPhase}
              </span>
            </>
          ) : (
            <>
              <StatusDot status="healthy" size={4} pulse />
              <span className="text-[11px] text-[var(--color-success)]">running</span>
            </>
          )}
        </IDEHeader>
        <div className="flex-1 min-h-0 overflow-hidden">
          <NotebookProvider value={notebookConfig}>
            <NotebookBoot onPhaseChange={handleBootPhase} onReady={handleBootReady} />
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
          <a
            href="/notebook"
            target="_blank"
            rel="noopener noreferrer"
            className="w-full flex items-center gap-3 px-5 py-4 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
          >
            <ExternalLink className="w-4 h-4" />
            <span>open in new tab</span>
          </a>
        </div>
      </div>
    </div>
  );
}
