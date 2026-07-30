"use client";

import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import {
  Check,
  Code,
  ExternalLink,
  Loader2,
  Share2,
  Square,
} from "lucide-react";
import {
  createNotebookSession,
  getNotebookSession,
  deleteNotebookSession,
  pingNotebookSession,
  getGatewayAuthToken,
  resolveAnalysisTrail,
  type AnalysisTrail,
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
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    ),
  }
);

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3300";
const NOTEBOOK_PROXY_URL = process.env.NEXT_PUBLIC_NOTEBOOK_PROXY_URL ?? "";
const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";
const NOTION_THREAD_EVENT = "sp:notion-thread-resolved";
const NOTION_THREAD_STORAGE_PREFIX = "sp:notion-thread:";
const SPA_NAVIGATE_EVENT = "spa:navigate";
const GATEWAY_PROJECT_STORAGE_KEY = "sp:gateway-project-id";
const GATEWAY_BRANCH_STORAGE_KEY = "sp:gateway-branch-id";
const KnownQueryParams = {
  project: "project",
  branch: "branch",
  filePath: "file",
  sessionId: "session_id",
} as const;

type NotionThreadWindow = Window & {
  __signalPilotNotionThreadId?: string;
  __signalPilotNotionThreadByFile?: Record<string, string>;
};

type AppState = "loading" | "no-session" | "booting" | "ready";

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

type ResolvedTrail = Pick<AnalysisTrail, "project_id" | "branch" | "thread_id" | "notebook_path">;

type RuntimeMode = "project" | "notion-trail" | "notebook";
type RuntimeProduct = "projects" | "notebooks";

const BOOT_PHASE_LABELS: Record<string, string> = {
  health: "connecting to runtime...",
  notion: "loading trail...",
  syncing: "syncing project files...",
  sessions: "preparing workspace...",
  ready: "running",
};

function resolveRuntimeMode({
  project,
  file,
  sessionId,
}: {
  project: string;
  file: string;
  sessionId: string;
}): RuntimeMode {
  if (project) return "project";
  if (isNotionTrailParams({ file, sessionId })) return "notion-trail";
  return "notebook";
}

function isNotionTrailParams({
  file,
  sessionId,
}: {
  file?: string | null;
  sessionId?: string | null;
}): boolean {
  return Boolean(
    sessionId?.startsWith("session-notion-") ||
      sessionId?.startsWith("session-slack-") ||
      file?.startsWith("signalpilot-notion-analyses/"),
  );
}

function isTrailSessionId(sessionId?: string): sessionId is string {
  return Boolean(
    sessionId?.startsWith("session-notion-") ||
      sessionId?.startsWith("session-slack-"),
  );
}

function IDEHeader({
  children,
  right,
}: {
  children?: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-background">
      <div className="flex items-center gap-3">
        <Code className="w-4 h-4 text-foreground" />
        <span className="text-xs font-bold uppercase tracking-wider text-foreground">
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
  const pathname = usePathname();
  const { planTier, isLoaded: subLoaded } = useSubscription();
  const isExternalView = pathname?.startsWith("/notebook") ?? false;
  const [browserSearch, setBrowserSearch] = useState(() =>
    typeof window === "undefined" ? "" : window.location.search,
  );

  const isPaid = PAID_TIERS.includes(planTier);
  const gated = IS_CLOUD_MODE && subLoaded && !isPaid;

  const nextSearch = searchParams.toString();
  const effectiveSearchParams = useMemo(
    () => new URLSearchParams(browserSearch || nextSearch),
    [browserSearch, nextSearch],
  );

  const urlProject = effectiveSearchParams.get("project") || "";
  const urlBranch = effectiveSearchParams.get("branch") || "";
  const urlSessionId = effectiveSearchParams.get("session_id") || "";
  const rawFile = effectiveSearchParams.get("file") || "";
  const urlFile = rawFile === "__new__project" ? "" : rawFile;
  const runtimeMode = resolveRuntimeMode({
    project: urlProject,
    file: urlFile,
    sessionId: urlSessionId,
  });
  const activeBranch = urlBranch || "main";
  const hasDeepLink = runtimeMode === "project"
    ? Boolean(urlProject)
    : Boolean(urlFile || urlSessionId);

  const [state, setState] = useState<AppState>("loading");
  const [launchStatus, setLaunchStatus] = useState(hasDeepLink ? "connecting to pod..." : "");
  const [notebookConfig, setNotebookConfig] = useState<NotebookConfig | null>(null);
  const [, setActiveNotebookSession] =
    useState<NotebookSession | null>(null);
  const [notionConnected, setNotionConnected] = useState(false);
  const [copied, setCopied] = useState(false);
  const [bootPhase, setBootPhase] = useState<string>("health");
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleBootPhase = useCallback((phase: string) => { setBootPhase(phase); }, []);
  const handleBootReady = useCallback(() => { setState("ready"); }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    setBrowserSearch(window.location.search);
  }, [nextSearch]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const syncBrowserSearch = () => {
      setBrowserSearch(window.location.search);
    };

    window.addEventListener("popstate", syncBrowserSearch);
    window.addEventListener(SPA_NAVIGATE_EVENT, syncBrowserSearch);
    return () => {
      window.removeEventListener("popstate", syncBrowserSearch);
      window.removeEventListener(SPA_NAVIGATE_EVENT, syncBrowserSearch);
    };
  }, []);

  function isNotionTrail(file = urlFile, sessionId = urlSessionId) {
    if (urlProject) {
      return false;
    }
    return isNotionTrailParams({ file, sessionId });
  }

  function clearNotionTrailProjectState() {
    if (typeof window === "undefined") {
      return;
    }

    window.localStorage.removeItem(GATEWAY_PROJECT_STORAGE_KEY);
    window.localStorage.removeItem(GATEWAY_BRANCH_STORAGE_KEY);
    window.localStorage.removeItem("sp:dbt-project-dir");

    const nextUrl = new URL(window.location.href);
    const before = nextUrl.toString();
    nextUrl.searchParams.delete(KnownQueryParams.project);
    nextUrl.searchParams.delete(KnownQueryParams.branch);
    if (nextUrl.toString() !== before) {
      window.history.replaceState(null, "", nextUrl.toString());
    }
  }

  function preserveResolvedProjectTrailInUrl(trail: ResolvedTrail) {
    if (!trail.project_id || typeof window === "undefined") {
      return;
    }

    const nextUrl = new URL(window.location.href);
    const before = nextUrl.toString();
    nextUrl.searchParams.set(KnownQueryParams.project, trail.project_id);
    nextUrl.searchParams.set(KnownQueryParams.branch, trail.branch || "main");
    nextUrl.searchParams.set(KnownQueryParams.filePath, trail.notebook_path || urlFile);
    nextUrl.searchParams.delete(KnownQueryParams.sessionId);

    window.localStorage.setItem(GATEWAY_PROJECT_STORAGE_KEY, trail.project_id);
    window.localStorage.setItem(GATEWAY_BRANCH_STORAGE_KEY, trail.branch || "main");

    if (nextUrl.toString() !== before) {
      window.history.replaceState(null, "", nextUrl.toString());
    }
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
      !isTrailSessionId(kernelSessionId) ||
      !isNotionTrail(urlFile, kernelSessionId) ||
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
      name: urlFile.split("/").pop() || "Notion request",
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
      clearNotionTrailProjectState();
    } catch (err) {
      console.warn("Failed to prime Notion trail editor state:", err);
    }
  }

  function preserveResolvedNotionSessionInUrl(kernelSessionId?: string) {
    if (
      !isTrailSessionId(kernelSessionId) ||
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
      !isNotionTrailParams({ file, sessionId: null }) ||
      typeof window === "undefined"
    ) {
      return undefined;
    }

    const win = window as NotionThreadWindow;
    const remembered =
      win.__signalPilotNotionThreadByFile?.[file] ??
      window.localStorage.getItem(`${NOTION_THREAD_STORAGE_PREFIX}${file}`) ??
      undefined;
    return isTrailSessionId(remembered) ? remembered : undefined;
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
      !isTrailSessionId(kernelSessionId) ||
      !isNotionTrail(urlFile, kernelSessionId) ||
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

  useEffect(() => {
    return () => {
      if (pingRef.current) {
        clearInterval(pingRef.current);
        pingRef.current = null;
      }
    };
  }, []);

  async function fetchNotionTraceThreads() {
    const token = await getGatewayAuthToken();
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;

    return fetch(`${GATEWAY_URL}/api/chat/traces/threads`, {
      headers,
    });
  }

  async function resolveNotionThreadId(): Promise<string | undefined> {
    if (isTrailSessionId(urlSessionId)) {
      return urlSessionId;
    }
    if (!isNotionTrailParams({ file: urlFile, sessionId: null })) {
      return undefined;
    }
    const remembered = getRememberedNotionThreadId(urlFile);
    if (remembered) {
      return remembered;
    }

    try {
      const resp = await fetchNotionTraceThreads();
      if (!resp.ok) {return undefined;}
      setNotionConnected(true);
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
      const matchThreadId = match?.thread_id;
      return isTrailSessionId(matchThreadId)
        ? matchThreadId
        : undefined;
    } catch (err) {
      console.warn("Failed to resolve Notion thread for notebook file:", err);
      return undefined;
    }
  }

  async function resolveTrailMetadata(): Promise<ResolvedTrail | undefined> {
    if (!isNotionTrail(urlFile, urlSessionId)) {
      return undefined;
    }
    try {
      const trail = await resolveAnalysisTrail({
        session_id: urlSessionId || undefined,
        file: urlFile || undefined,
      });
      const resolved = {
        project_id: trail.project_id,
        branch: trail.branch || trail.default_branch || "main",
        thread_id: trail.thread_id,
        notebook_path: trail.notebook_path,
      };
      preserveResolvedProjectTrailInUrl(resolved);
      return resolved;
    } catch (err) {
      console.warn("Failed to resolve durable analysis trail:", err);
      return undefined;
    }
  }

  async function buildConfig(
    sessionId: string,
    apiKey?: string,
    product: RuntimeProduct = runtimeMode === "project" ? "projects" : "notebooks",
    trail?: ResolvedTrail,
  ): Promise<NotebookConfig> {
    if (product === "projects") {
      return {
        gatewayUrl: GATEWAY_URL,
        notebookProxyUrl: NOTEBOOK_PROXY_URL,
        product: "projects",
        sessionId,
        getToken: getGatewayAuthToken,
        apiKey,
        project: urlProject || undefined,
        branch: urlProject ? activeBranch : undefined,
        file: urlFile || undefined,
        notionConnected,
      };
    }

    const resolvedTrail = trail ?? await resolveTrailMetadata();
    const kernelSessionId = resolvedTrail?.thread_id ?? await resolveNotionThreadId();
    const trailFile = resolvedTrail?.notebook_path || urlFile;
    const isProjectBackedTrail = Boolean(resolvedTrail?.project_id);
    if (!isProjectBackedTrail && isNotionTrail(trailFile, kernelSessionId || urlSessionId)) {
      clearNotionTrailProjectState();
    }
    rememberResolvedNotionThread(kernelSessionId);
    if (!isProjectBackedTrail) {
      preserveResolvedNotionSessionInUrl(kernelSessionId);
      primeNotionTrailChrome(kernelSessionId);
      primeNotionTrailEditorState(kernelSessionId);
    }
    return {
      gatewayUrl: GATEWAY_URL,
      notebookProxyUrl: NOTEBOOK_PROXY_URL,
      product: isProjectBackedTrail ? "projects" : "notebooks",
      sessionId,
      getToken: getGatewayAuthToken,
      kernelSessionId,
      apiKey,
      project: resolvedTrail?.project_id,
      branch: resolvedTrail?.branch,
      file: trailFile || undefined,
      notionConnected: notionConnected || Boolean(kernelSessionId),
    };
  }

  useEffect(() => {
    if (IS_CLOUD_MODE && !subLoaded) return;
    if (gated) {
      setState("no-session");
      return;
    }
    if (state === "booting" || state === "ready") {
      return;
    }

    let cancelled = false;

    async function init() {
      setState((s) => (s === "booting" || s === "ready" ? s : "loading"));

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
          const sessionProject = session.project_id || "";
          const sessionBranch = session.branch || "main";
          if (runtimeMode === "project") {
            if (sessionProject !== urlProject || sessionBranch !== activeBranch) {
              console.log("[projects] Session project/branch mismatch — deleting stale session");
              await deleteNotebookSession().catch(() => {});
            } else {
              const config = await buildConfig(session.id, apiKey, "projects");
              setNotebookConfig(config);
              setState("booting");
              startPing();
              return;
            }
          } else if (runtimeMode === "notion-trail") {
            const trail = await resolveTrailMetadata();
            if (
              trail &&
              sessionProject === trail.project_id &&
              sessionBranch === (trail.branch || "main")
            ) {
              const config = await buildConfig(session.id, apiKey, "notebooks", trail);
              setNotebookConfig(config);
              setState("booting");
              startPing();
              return;
            }
            await deleteNotebookSession().catch(() => {});
          } else if (sessionProject) {
            console.log("[projects] Project session mismatch — deleting stale session");
            await deleteNotebookSession().catch(() => {});
          } else if (hasDeepLink) {
            const config = await buildConfig(session.id, apiKey, "notebooks");
            setNotebookConfig(config);
            setState("booting");
            startPing();
            return;
          } else {
            setActiveNotebookSession(session);
            setState("no-session");
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
    };
  }, [subLoaded, gated, runtimeMode, urlProject, activeBranch, urlFile, urlSessionId, hasDeepLink]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (notebookConfig && (state === "ready" || state === "booting")) {
      const isResolvedProjectTrail =
        !urlProject &&
        isNotionTrail(urlFile, urlSessionId) &&
        Boolean(notebookConfig.project);
      const nextProduct: RuntimeProduct = urlProject
        ? "projects"
        : isResolvedProjectTrail
          ? notebookConfig.product ?? "notebooks"
        : isNotionTrail(urlFile, urlSessionId)
          ? "notebooks"
          : notebookConfig.product ?? "notebooks";
      const newFile = urlFile || undefined;
      const newKernelSessionId = nextProduct === "notebooks" && isTrailSessionId(urlSessionId)
        ? urlSessionId
        : notebookConfig.kernelSessionId;
      const newProject = urlProject
        ? urlProject
        : isResolvedProjectTrail
          ? notebookConfig.project
          : undefined;
      const newBranch = urlProject
        ? activeBranch
        : isResolvedProjectTrail
          ? notebookConfig.branch
          : undefined;
      if (
        nextProduct !== notebookConfig.product ||
        newProject !== notebookConfig.project ||
        newBranch !== notebookConfig.branch ||
        newFile !== notebookConfig.file ||
        newKernelSessionId !== notebookConfig.kernelSessionId ||
        notionConnected !== notebookConfig.notionConnected
      ) {
        setNotebookConfig((prev) =>
          prev
            ? {
                ...prev,
                product: nextProduct,
                project: newProject,
                branch: newBranch,
                file: newFile,
                kernelSessionId: newKernelSessionId,
                notionConnected,
              }
            : prev,
        );
      }
    }
  }, [urlProject, urlBranch, urlFile, urlSessionId, state, notionConnected]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const kernelSessionId = notebookConfig?.kernelSessionId;
    if (!isTrailSessionId(kernelSessionId)) {
      return;
    }
    rememberResolvedNotionThread(kernelSessionId);
    preserveResolvedNotionSessionInUrl(kernelSessionId);
    primeNotionTrailChrome(kernelSessionId);
    primeNotionTrailEditorState(kernelSessionId);
  }, [notebookConfig?.kernelSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function launch(
    existingApiKey?: string,
    product: RuntimeProduct = runtimeMode === "project" ? "projects" : "notebooks",
  ) {
    setState("loading");
    setLaunchStatus(product === "projects" ? "creating project workspace..." : "creating notebook runtime...");
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

      const trail = product === "notebooks" && runtimeMode === "notion-trail"
        ? await resolveTrailMetadata()
        : undefined;
      const session = await createNotebookSession(
        trail
          ? { project_id: trail.project_id, branch: trail.branch || "main" }
          : product === "projects" && urlProject
          ? { project_id: urlProject, branch: activeBranch }
          : { project_id: null },
      );
      setActiveNotebookSession(session);
      if (!session.id) {
        toast("Session created but no ID returned", "error");
        setState("no-session");
        return;
      }
      setLaunchStatus("waiting for pod...");
      const config = await buildConfig(session.id, apiKey, product, trail);

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
    if (pingRef.current) { clearInterval(pingRef.current); pingRef.current = null; }
  }

  function getEffectiveNotebookConfig(config: NotebookConfig): NotebookConfig {
    if (config.product !== "notebooks" || !isNotionTrail(urlFile, urlSessionId)) {
      return config;
    }

    const kernelSessionId = isTrailSessionId(urlSessionId)
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

  function notebookPopoutHref(config: NotebookConfig): string {
    const params = new URLSearchParams();
    if (config.product === "projects") {
      const projectId = urlProject || config.project;
      const branch = urlProject ? activeBranch : config.branch;
      if (projectId) params.set("project", projectId);
      if (projectId) params.set("branch", branch || "main");
      if (urlFile || config.file) {
        params.set("file", urlFile || config.file || "");
      }
    } else {
      if (urlFile) params.set("file", urlFile);
      const sessionId = urlSessionId || config.kernelSessionId;
      if (sessionId) params.set("session_id", sessionId);
    }
    const qs = params.toString();
    return `/notebook${qs ? `?${qs}` : ""}`;
  }

  // ─── Render: Paywall (free-tier cloud users) ──────────────────
  if (gated) {
    return <NotebooksProjectsPaywall />;
  }

  // ─── Render: Loading ──────────────────────────────────────────
  if (state === "loading") {
    return (
      <div className="flex flex-col h-screen bg-background text-foreground">
        <IDEHeader>
          <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />
          <span className="text-[11px] text-muted-foreground">{launchStatus}</span>
        </IDEHeader>
        <div className="flex-1 flex flex-col items-center justify-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
          <span className="text-xs text-muted-foreground tracking-wider uppercase">
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
      effectiveNotebookConfig.product ?? "",
      effectiveNotebookConfig.sessionId,
      effectiveNotebookConfig.project ?? "",
      effectiveNotebookConfig.branch ?? "",
      effectiveNotebookConfig.file ?? "",
      effectiveNotebookConfig.kernelSessionId ?? "",
    ].join(":");
    return (
      <div className="flex flex-col h-screen bg-background text-foreground">
        <IDEHeader
          right={
            <>
              <button
                onClick={handleShare}
                className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-muted-foreground border border-border hover:border-muted-foreground hover:text-foreground transition-all tracking-wider uppercase"
              >
                {copied ? <Check className="w-3 h-3" /> : <Share2 className="w-3 h-3" />}
                {copied ? "copied" : "share"}
              </button>
              {!isExternalView && (
                <a
                  href={notebookPopoutHref(effectiveNotebookConfig)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-muted-foreground border border-border hover:border-muted-foreground hover:text-foreground transition-all tracking-wider uppercase"
                >
                  <ExternalLink className="w-3 h-3" /> external
                </a>
              )}
              <button
                onClick={stop}
                className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-muted-foreground border border-border hover:border-destructive hover:text-destructive transition-all tracking-wider uppercase"
              >
                <Square className="w-3 h-3" /> stop
              </button>
            </>
          }
        >
          {state === "booting" ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />
              <span className="text-[11px] text-muted-foreground">
                {BOOT_PHASE_LABELS[bootPhase] || bootPhase}
              </span>
            </>
          ) : (
            <>
              <StatusDot status="healthy" size={4} pulse />
              <span className="text-[11px] text-green-500">running</span>
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

  // ─── Render: No session (landing) ─────────────────────────────
  return (
    <div className="p-8 animate-fade-in">
      <div className="max-w-6xl mx-auto mt-16">
        <div className="flex items-center gap-3 mb-6">
          <Code className="w-6 h-6 text-foreground" />
          <h1 className="text-lg font-bold uppercase tracking-wider text-foreground">
            SignalPilot IDE
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-3 mb-8">
          <button
            onClick={() => launch(undefined, "notebooks")}
            className="flex items-center gap-3 px-5 py-3 bg-primary text-primary-foreground text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90"
          >
            <Code className="w-4 h-4" />
            <span>open notebook runtime</span>
          </button>
          <a
            href="/projects"
            className="flex items-center gap-3 px-5 py-3 text-xs text-muted-foreground border border-border hover:border-muted-foreground hover:text-foreground transition-all tracking-wider uppercase"
          >
            <ExternalLink className="w-4 h-4" />
            <span>back to projects</span>
          </a>
        </div>
      </div>
    </div>
  );
}
