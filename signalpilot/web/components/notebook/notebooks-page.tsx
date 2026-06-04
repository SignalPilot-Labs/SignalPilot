"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import {
  Loader2,
  Code,
  ExternalLink,
  Square,
  Share2,
  Check,
  RefreshCw,
} from "lucide-react";
import {
  createNotebookSession,
  getNotebookSession,
  deleteNotebookSession,
  pingNotebookSession,
  getGatewayAuthToken,
  type NotebookSession,
} from "~/lib/api";
import { StatusDot } from "~/components/ui/data-viz";
import { useToast } from "~/components/ui/toast";
import {
  NotebookProvider,
  type NotebookConfig,
} from "~/components/notebook/notebook-context";
import { NotebooksProjectsPaywall } from "~/components/billing/notebooks-projects-paywall";
import { useSubscription } from "~/lib/subscription-context";

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
const NOTEBOOK_PROXY_URL = process.env.NEXT_PUBLIC_NOTEBOOK_PROXY_URL ?? "";
const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";
const NOTION_THREAD_EVENT = "sp:notion-thread-resolved";
const NOTION_THREAD_STORAGE_PREFIX = "sp:notion-thread:";

type NotionThreadWindow = Window & {
  __signalPilotNotionThreadId?: string;
  __signalPilotNotionThreadByFile?: Record<string, string>;
};

type AppState = "loading" | "no-session" | "booting" | "ready";

type NotionConversation = {
  id: string;
  title: string;
  source?: string;
  status?: string;
  notebook_path?: string;
  created_at?: number;
  updated_at?: number;
};

type ChatTraceThread = {
  thread_id: string;
  session_id: string;
  title?: string;
  source?: string;
  status?: string;
  notebook_path?: string;
  created_at?: number;
  updated_at?: number;
};

const BOOT_PHASE_LABELS: Record<string, string> = {
  health: "connecting to runtime...",
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
          SignalPilot notebook
        </span>
        {children}
      </div>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </div>
  );
}

export default function NotebooksPage() {
  const { toast } = useToast();
  const searchParams = useSearchParams();
  const { planTier, isLoaded: subLoaded } = useSubscription();

  const isPaid = PAID_TIERS.includes(planTier);
  const gated = IS_CLOUD_MODE && subLoaded && !isPaid;

  const urlSessionId = searchParams.get("session_id") || "";
  const rawFile = searchParams.get("file") || "";
  const urlFile = rawFile === "__new__project" ? "" : rawFile;
  const hasDeepLink = Boolean(urlFile || urlSessionId);

  const [state, setState] = useState<AppState>("loading");
  const [launchStatus, setLaunchStatus] = useState(hasDeepLink ? "connecting to pod..." : "");
  const [notebookConfig, setNotebookConfig] = useState<NotebookConfig | null>(null);
  const [, setActiveNotebookSession] =
    useState<NotebookSession | null>(null);
  const [notionConversations, setNotionConversations] = useState<
    NotionConversation[]
  >([]);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [bootPhase, setBootPhase] = useState<string>("health");
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleBootPhase = useCallback((phase: string) => { setBootPhase(phase); }, []);
  const handleBootReady = useCallback(() => { setState("ready"); }, []);

  function isNotionTrail(file = urlFile, sessionId = urlSessionId) {
    return (
      sessionId.startsWith("session-notion-") ||
      file.startsWith("signalpilot-notion-analyses/")
    );
  }

  function primeNotionTrailChrome(kernelSessionId?: string) {
    if (!isNotionTrail(urlFile, kernelSessionId || urlSessionId) || typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(
      "sp:sidebar",
      JSON.stringify({
        selectedPanel: "ai",
        isSidebarOpen: true,
        isDeveloperPanelOpen: false,
        selectedDeveloperPanelTab: "errors",
      }),
    );
  }

  function primeNotionTrailEditorState(kernelSessionId?: string) {
    if (
      !kernelSessionId?.startsWith("session-notion-") ||
      !urlFile.startsWith("signalpilot-notion-analyses/") ||
      typeof window === "undefined"
    ) {
      return;
    }

    const tabId = `notion-${kernelSessionId}`;
    const targetTab = {
      id: tabId,
      path: urlFile,
      type: "notebook",
      sessionId: kernelSessionId,
      name: urlFile.split("/").pop() || "Notion analysis",
    };

    try {
      const rawTabs = window.localStorage.getItem("sp:open-tabs");
      const existingTabs = rawTabs ? JSON.parse(rawTabs) : [];
      const tabs = Array.isArray(existingTabs) ? existingTabs : [];
      const nextTabs = [
        targetTab,
        ...tabs.filter((tab) => tab?.id !== tabId && tab?.path !== urlFile),
      ];
      window.localStorage.setItem("sp:open-tabs", JSON.stringify(nextTabs));
      window.localStorage.setItem("sp:active-tab-id", JSON.stringify(tabId));
      window.localStorage.removeItem("sp:dbt-project-dir");
    } catch (err) {
      console.warn("Failed to prime Notion trail editor state:", err);
    }
  }

  function preserveResolvedNotionSessionInUrl(kernelSessionId?: string) {
    if (
      !kernelSessionId?.startsWith("session-notion-") ||
      urlSessionId ||
      typeof window === "undefined"
    ) {
      return;
    }

    const nextUrl = new URL(window.location.href);
    nextUrl.searchParams.set("session_id", kernelSessionId);
    window.history.replaceState(null, "", nextUrl.toString());
  }

  function getRememberedNotionThreadId(file: string): string | undefined {
    if (
      !file.startsWith("signalpilot-notion-analyses/") ||
      typeof window === "undefined"
    ) {
      return undefined;
    }

    const win = window as NotionThreadWindow;
    const remembered =
      win.__signalPilotNotionThreadByFile?.[file] ??
      window.localStorage.getItem(`${NOTION_THREAD_STORAGE_PREFIX}${file}`) ??
      undefined;
    return remembered?.startsWith("session-notion-") ? remembered : undefined;
  }

  function restoreMissingNotionSessionInUrl() {
    if (urlSessionId || typeof window === "undefined") {
      return;
    }

    const remembered = getRememberedNotionThreadId(urlFile);
    if (!remembered) {
      return;
    }

    const nextUrl = new URL(window.location.href);
    nextUrl.searchParams.set("session_id", remembered);
    window.history.replaceState(null, "", nextUrl.toString());
  }

  function rememberResolvedNotionThread(kernelSessionId?: string) {
    if (
      !kernelSessionId?.startsWith("session-notion-") ||
      !urlFile.startsWith("signalpilot-notion-analyses/") ||
      typeof window === "undefined"
    ) {
      return;
    }

    const win = window as NotionThreadWindow;
    win.__signalPilotNotionThreadId = kernelSessionId;
    win.__signalPilotNotionThreadByFile = {
      ...(win.__signalPilotNotionThreadByFile ?? {}),
      [urlFile]: kernelSessionId,
    };
    window.localStorage.setItem(
      `${NOTION_THREAD_STORAGE_PREFIX}${urlFile}`,
      kernelSessionId,
    );
    window.dispatchEvent(
      new CustomEvent(NOTION_THREAD_EVENT, {
        detail: { file: urlFile, sessionId: kernelSessionId },
      }),
    );
  }

  useEffect(() => {
    restoreMissingNotionSessionInUrl();
  }, [urlFile, urlSessionId]);

  function toNotionConversation(thread: ChatTraceThread): NotionConversation {
    return {
      id: thread.thread_id,
      title: thread.title || "Notion analysis",
      source: thread.source,
      status: thread.status,
      notebook_path: thread.notebook_path,
      created_at: thread.created_at,
      updated_at: thread.updated_at,
    };
  }

  async function fetchNotionTraceThreads() {
    const token = await getGatewayAuthToken();
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;

    return fetch(`${GATEWAY_URL}/api/chat/traces/threads?source=notion`, {
      headers,
    });
  }

  async function resolveNotionThreadId(): Promise<string | undefined> {
    if (urlSessionId.startsWith("session-notion-")) {
      return urlSessionId;
    }
    if (!urlFile.startsWith("signalpilot-notion-analyses/")) {
      return undefined;
    }

    try {
      const resp = await fetchNotionTraceThreads();
      if (!resp.ok) {return undefined;}
      const data = (await resp.json()) as {
        threads?: ChatTraceThread[];
      };
      const match = (data.threads ?? []).find((thread) => {
        const notebookPath = thread.notebook_path || "";
        return (
          notebookPath === urlFile ||
          notebookPath.endsWith(`/${urlFile}`) ||
          urlFile.endsWith(notebookPath)
        );
      });
      return match?.thread_id?.startsWith("session-notion-")
        ? match.thread_id
        : undefined;
    } catch (err) {
      console.warn("Failed to resolve Notion thread for notebook file:", err);
      return undefined;
    }
  }

  async function buildConfig(sessionId: string, apiKey?: string): Promise<NotebookConfig> {
    const kernelSessionId = await resolveNotionThreadId();
    rememberResolvedNotionThread(kernelSessionId);
    preserveResolvedNotionSessionInUrl(kernelSessionId);
    primeNotionTrailChrome(kernelSessionId);
    primeNotionTrailEditorState(kernelSessionId);
    return {
      gatewayUrl: GATEWAY_URL,
      notebookProxyUrl: NOTEBOOK_PROXY_URL,
      product: "notebooks",
      sessionId,
      getToken: getGatewayAuthToken,
      kernelSessionId,
      apiKey,
      file: urlFile || undefined,
    };
  }

  async function loadNotionConversations() {
    setOverviewLoading(true);
    setOverviewError(null);
    try {
      const resp = await fetchNotionTraceThreads();
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const data = (await resp.json()) as {
        threads?: ChatTraceThread[];
      };
      setNotionConversations(
        (data.threads ?? []).map(toNotionConversation).filter(
          (conversation) =>
            conversation.source === "notion" ||
            conversation.id.startsWith("session-notion-"),
        ),
      );
    } catch (err) {
      setOverviewError(err instanceof Error ? err.message : String(err));
      setNotionConversations([]);
    } finally {
      setOverviewLoading(false);
    }
  }

  useEffect(() => {
    if (IS_CLOUD_MODE && !subLoaded) return;
    if (gated) {
      setState("no-session");
      return;
    }

    let cancelled = false;

    async function init() {
      let apiKey: string | undefined;
      if (!IS_CLOUD_MODE) {
        try {
          const keyResp = await fetch("/api/local-key");
          const keyData = (await keyResp.json()) as { key?: string };
          if (keyData?.key) apiKey = keyData.key;
        } catch (err) {
          console.warn("Failed to fetch API key:", err);
        }
      }

      try {
        const session = await getNotebookSession() as any;
        if (!cancelled && session?.status === "running" && session.id && session.notebook_url) {
          if (session.project_id) {
            console.log("[notebooks] Project session mismatch — deleting stale session");
            await deleteNotebookSession().catch(() => {});
          } else if (hasDeepLink) {
            const config = await buildConfig(session.id, apiKey);
            setNotebookConfig(config);
            setState("booting");
            startPing();
            return;
          } else {
            setActiveNotebookSession(session);
            setState("no-session");
            void loadNotionConversations();
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
  }, [subLoaded, gated]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (notebookConfig && (state === "ready" || state === "booting")) {
      const newFile = urlFile || undefined;
      const newKernelSessionId = urlSessionId.startsWith("session-notion-")
        ? urlSessionId
        : notebookConfig.kernelSessionId;
      if (
        newFile !== notebookConfig.file ||
        newKernelSessionId !== notebookConfig.kernelSessionId
      ) {
        setNotebookConfig((prev) =>
          prev
            ? {
                ...prev,
                file: newFile,
                kernelSessionId: newKernelSessionId,
              }
            : prev,
        );
      }
    }
  }, [urlFile, urlSessionId, state]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!notebookConfig?.kernelSessionId?.startsWith("session-notion-")) {
      return;
    }
    rememberResolvedNotionThread(notebookConfig.kernelSessionId);
    preserveResolvedNotionSessionInUrl(notebookConfig.kernelSessionId);
    primeNotionTrailChrome(notebookConfig.kernelSessionId);
    primeNotionTrailEditorState(notebookConfig.kernelSessionId);
  }, [notebookConfig?.kernelSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function launch(existingApiKey?: string) {
    setState("loading");
    setLaunchStatus("creating session...");
    try {
      let apiKey = existingApiKey;
      if (!apiKey && !IS_CLOUD_MODE) {
        try {
          const keyResp = await fetch("/api/local-key");
          const keyData = (await keyResp.json()) as { key?: string };
          if (keyData?.key) apiKey = keyData.key;
        } catch (err) {
          console.warn("Failed to fetch API key:", err);
        }
      }

      const session = await createNotebookSession();
      setActiveNotebookSession(session);
      if (!session.id) {
        toast("Session created but no ID returned", "error");
        setState("no-session");
        return;
      }
      setLaunchStatus("waiting for pod...");
      const config = await buildConfig(session.id, apiKey);

      setNotebookConfig(config);
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
    setActiveNotebookSession(null);
    setNotionConversations([]);
    if (pingRef.current) { clearInterval(pingRef.current); pingRef.current = null; }
  }

  function getEffectiveNotebookConfig(config: NotebookConfig): NotebookConfig {
    if (!isNotionTrail(urlFile, urlSessionId)) {
      return config;
    }

    const kernelSessionId = urlSessionId.startsWith("session-notion-")
      ? urlSessionId
      : config.kernelSessionId;
    return {
      ...config,
      file: urlFile || config.file,
      kernelSessionId,
    };
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

  // ─── Render: Booting / Ready ──────────────────────────────────
  if ((state === "booting" || state === "ready") && notebookConfig) {
    const effectiveNotebookConfig = getEffectiveNotebookConfig(notebookConfig);
    const bootKey = [
      effectiveNotebookConfig.sessionId,
      effectiveNotebookConfig.file ?? "",
      effectiveNotebookConfig.kernelSessionId ?? "",
    ].join(":");
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
                href={`${GATEWAY_URL}/notebook/${effectiveNotebookConfig.sessionId}/`}
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
          <NotebookProvider key={bootKey} value={effectiveNotebookConfig}>
            <NotebookBoot key={bootKey} onPhaseChange={handleBootPhase} onReady={handleBootReady} />
          </NotebookProvider>
        </div>
      </div>
    );
  }

  // ─── Render: Paywall (free-tier cloud users) ──────────────────
  if (gated) {
    return <NotebooksProjectsPaywall />;
  }

  // ─── Render: No session (landing) ─────────────────────────────
  return (
    <div className="p-8 animate-fade-in">
      <div className="max-w-4xl mx-auto mt-16">
        <div className="flex items-center gap-3 mb-6">
          <Code className="w-6 h-6 text-[var(--color-text)]" />
          <h1 className="text-lg font-bold uppercase tracking-wider text-[var(--color-text)]">
            SignalPilot notebooks
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-3 mb-8">
          <button
            onClick={() => launch()}
            className="flex items-center gap-3 px-5 py-3 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90"
          >
            <Code className="w-4 h-4" />
            <span>open notebook runtime</span>
          </button>
          <button
            onClick={() => loadNotionConversations()}
            className="flex items-center gap-3 px-5 py-3 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
            disabled={overviewLoading}
          >
            {overviewLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            <span>refresh</span>
          </button>
        </div>
        <NotionConversationList
          conversations={notionConversations}
          loading={overviewLoading}
          error={overviewError}
        />
      </div>
    </div>
  );
}

function NotionConversationList({
  conversations,
  loading,
  error,
}: {
  conversations: NotionConversation[];
  loading: boolean;
  error: string | null;
}) {
  if (loading && conversations.length === 0) {
    return (
      <div className="border border-[var(--color-border)] px-5 py-10 flex items-center justify-center gap-3 text-xs text-[var(--color-text-dim)] uppercase tracking-wider">
        <Loader2 className="w-4 h-4 animate-spin" />
        loading notion analyses...
      </div>
    );
  }

  if (error) {
    return (
      <div className="border border-[var(--color-error)]/40 px-5 py-4 text-xs text-[var(--color-error)]">
        Could not load Notion analyses: {error}
      </div>
    );
  }

  if (conversations.length === 0) {
    return (
      <div className="border border-[var(--color-border)] px-5 py-10 text-sm text-[var(--color-text-dim)]">
        No Notion analysis notebooks yet.
      </div>
    );
  }

  return (
    <div className="border border-[var(--color-border)] divide-y divide-[var(--color-border)]">
      {conversations.map((conversation) => {
        const file = conversation.notebook_path || "";
        const href = file
          ? `/notebooks?file=${encodeURIComponent(file)}&session_id=${encodeURIComponent(conversation.id)}`
          : `/notebooks?session_id=${encodeURIComponent(conversation.id)}`;
        const status = conversation.status || "saved";
        return (
          <a
            key={conversation.id}
            href={href}
            className="flex items-center gap-4 px-5 py-4 hover:bg-[var(--color-bg-hover)] transition-colors"
          >
            <div className="min-w-0 flex-1">
              <div className="text-sm text-[var(--color-text)] truncate">
                {conversation.title || "Notion analysis"}
              </div>
              <div className="text-[11px] text-[var(--color-text-dim)] font-mono truncate mt-1">
                {file || conversation.id}
              </div>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <span className="text-[10px] uppercase tracking-wider text-[var(--color-text-dim)] border border-[var(--color-border)] px-2 py-1">
                {status}
              </span>
              <span className="text-[11px] text-[var(--color-text-dim)]">
                {formatConversationTime(conversation.updated_at)}
              </span>
              <ExternalLink className="w-4 h-4 text-[var(--color-text-dim)]" />
            </div>
          </a>
        );
      })}
    </div>
  );
}

function formatConversationTime(value?: number): string {
  if (!value) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value * 1000));
}
