"use client";

import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import {
  Check,
  Code,
  ExternalLink,
  Github,
  Loader2,
  Share2,
  RefreshCw,
  Square,
} from "lucide-react";
import {
  createNotebookSession,
  getGitHubInstallations,
  getNotebookSession,
  getNotionOAuthInstallations,
  getProjects,
  deleteNotebookSession,
  pingNotebookSession,
  getGatewayAuthToken,
  getWorkspaceProjects,
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
import { NotionIcon } from "~/components/branding/notion-icon";
import { useSubscription } from "~/lib/subscription-context";
import { DbtProjectActions } from "@/components/home/dbt-project-actions";
import { DbtProjectList } from "@/components/home/dbt-project-list";
import { Header } from "@/components/home/components";
import { Button } from "@/components/ui/button";
import { dbtProjectDirAtom } from "@/components/editor/dbt/use-dbt";
import { gatewayBranchIdAtom as persistedGatewayBranchIdAtom } from "@/core/branch/branch-state";
import { KnownQueryParams } from "@/core/constants";
import {
  GATEWAY_BRANCH_STORAGE_KEY,
  GATEWAY_PROJECT_STORAGE_KEY,
  gatewayBranchIdAtom,
  gatewayProjectIdAtom,
} from "@/core/network/gateway-state";
import {
  setGatewayBranchId,
  setGatewayProjectId,
} from "@/core/network/api";
import { isNotionTrailParams } from "@/core/notion/trail";
import { SPA_NAVIGATE_EVENT } from "@/core/router/spa-navigate";
import { store } from "@/core/state/jotai";

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

type ResolvedTrail = Pick<AnalysisTrail, "project_id" | "branch" | "thread_id" | "notebook_path">;

type RuntimeMode = "project" | "notion-trail" | "notebook";
type RuntimeProduct = "projects" | "notebooks";

type OverviewState = {
  loading: boolean;
  projectCount: number;
  githubConnected: boolean;
  notionConnected: boolean;
  error: string | null;
};

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

function hasUsableNotionInstallation(
  installations: Array<{ status?: string; config?: { enabled?: boolean } | null }>,
): boolean {
  return installations.some(
    (installation) => installation.status !== "disconnected" && installation.config?.enabled === true,
  );
}

function hasUsableGitHubInstallation(data: unknown): boolean {
  const installations = Array.isArray(data)
    ? data
    : (data as { installations?: unknown[] } | null)?.installations ?? [];
  return installations.some(
    (installation) =>
      installation !== null &&
      typeof installation === "object" &&
      (installation as { status?: string }).status !== "disconnected",
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
  const [notionConversations, setNotionConversations] = useState<
    NotionConversation[]
  >([]);
  const [overview, setOverview] = useState<OverviewState>({
    loading: true,
    projectCount: 0,
    githubConnected: false,
    notionConnected: false,
    error: null,
  });
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [projectListRefreshNonce, setProjectListRefreshNonce] = useState(0);
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

    setGatewayProjectId(null);
    setGatewayBranchId(null);
    store.set(gatewayProjectIdAtom, null);
    store.set(gatewayBranchIdAtom, null);
    store.set(persistedGatewayBranchIdAtom, null);
    store.set(dbtProjectDirAtom, null);
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

  function toNotionConversation(thread: ChatTraceThread): NotionConversation {
    return {
      id: thread.thread_id,
      title: thread.title || "Notion request",
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

    return fetch(`${GATEWAY_URL}/api/chat/traces/threads`, {
      headers,
    });
  }

  async function resolveNotionThreadId(
    notionConnected = overview.notionConnected,
  ): Promise<string | undefined> {
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
    if (!notionConnected) {
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
      return {
        project_id: trail.project_id,
        branch: trail.branch || trail.default_branch || "main",
        thread_id: trail.thread_id,
        notebook_path: trail.notebook_path,
      };
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
        notionConnected: overview.notionConnected,
      };
    }

    const resolvedTrail = trail ?? await resolveTrailMetadata();
    const kernelSessionId = resolvedTrail?.thread_id ?? await resolveNotionThreadId(overview.notionConnected);
    const trailFile = resolvedTrail?.notebook_path || urlFile;
    if (isNotionTrail(trailFile, kernelSessionId || urlSessionId)) {
      clearNotionTrailProjectState();
    }
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
      project: resolvedTrail?.project_id,
      branch: resolvedTrail?.branch,
      file: trailFile || undefined,
      notionConnected: overview.notionConnected,
    };
  }

  async function loadNotionConversations(
    notionConnected = overview.notionConnected,
  ) {
    if (!notionConnected) {
      setOverviewError(null);
      setNotionConversations([]);
      return;
    }
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
            isTrailSessionId(conversation.id),
        ),
      );
    } catch (err) {
      setOverviewError(err instanceof Error ? err.message : String(err));
      setNotionConversations([]);
    } finally {
      setOverviewLoading(false);
    }
  }

  async function loadOverview() {
    setOverview((prev) => ({ ...prev, loading: true, error: null }));

    const [projectsResult, githubResult, notionResult] = await Promise.allSettled([
      getWorkspaceProjects("active")
        .then((result) => result.total)
        .catch(() => getProjects().then((projects) => projects.length)),
      getGitHubInstallations(),
      getNotionOAuthInstallations(),
    ]);

    const nextOverview: OverviewState = {
      loading: false,
      projectCount:
        projectsResult.status === "fulfilled" ? projectsResult.value : 0,
      githubConnected:
        githubResult.status === "fulfilled" &&
        hasUsableGitHubInstallation(githubResult.value),
      notionConnected:
        notionResult.status === "fulfilled" &&
        hasUsableNotionInstallation(notionResult.value),
      error:
        projectsResult.status === "rejected" &&
        githubResult.status === "rejected" &&
        notionResult.status === "rejected"
          ? "Could not load workspace overview"
          : null,
    };

    setOverview(nextOverview);
    if (nextOverview.notionConnected) {
      await loadNotionConversations(true);
    } else {
      setOverviewError(null);
      setNotionConversations([]);
    }
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
            void loadOverview();
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
        void loadOverview();
      }
    }

    init();
    return () => {
      cancelled = true;
    };
  }, [subLoaded, gated, runtimeMode, urlProject, activeBranch, urlFile, urlSessionId, hasDeepLink]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (notebookConfig && (state === "ready" || state === "booting")) {
      const nextProduct: RuntimeProduct = urlProject
        ? "projects"
        : isNotionTrail(urlFile, urlSessionId)
          ? "notebooks"
          : notebookConfig.product ?? "notebooks";
      const newFile = urlFile || undefined;
      const newKernelSessionId = nextProduct === "notebooks" && isTrailSessionId(urlSessionId)
        ? urlSessionId
        : notebookConfig.kernelSessionId;
      const newProject = nextProduct === "projects" ? urlProject || undefined : undefined;
      const newBranch = nextProduct === "projects" && urlProject ? activeBranch : undefined;
      if (
        nextProduct !== notebookConfig.product ||
        newProject !== notebookConfig.project ||
        newBranch !== notebookConfig.branch ||
        newFile !== notebookConfig.file ||
        newKernelSessionId !== notebookConfig.kernelSessionId ||
        overview.notionConnected !== notebookConfig.notionConnected
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
                notionConnected: overview.notionConnected,
              }
            : prev,
        );
      }
    }
  }, [urlProject, urlBranch, urlFile, urlSessionId, state, overview.notionConnected]); // eslint-disable-line react-hooks/exhaustive-deps

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
    setNotionConversations([]);
    void loadOverview();
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
      if (urlProject) params.set("project", urlProject);
      if (urlProject) params.set("branch", activeBranch);
      if (urlFile) params.set("file", urlFile);
    } else {
      if (urlFile) params.set("file", urlFile);
      const sessionId = urlSessionId || config.kernelSessionId;
      if (sessionId) params.set("session_id", sessionId);
    }
    const qs = params.toString();
    return `/notebook${qs ? `?${qs}` : ""}`;
  }

  async function refreshOverview() {
    await loadOverview();
  }

  async function refreshProjectsSurface() {
    setProjectListRefreshNonce((nonce) => nonce + 1);
    await loadOverview();
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
                  href={notebookPopoutHref(effectiveNotebookConfig)}
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
          <Code className="w-6 h-6 text-[var(--color-text)]" />
          <h1 className="text-lg font-bold uppercase tracking-wider text-[var(--color-text)]">
            SignalPilot IDE
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-3 mb-8">
          <button
            onClick={() => launch(undefined, "notebooks")}
            className="flex items-center gap-3 px-5 py-3 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90"
          >
            <Code className="w-4 h-4" />
            <span>open notebook runtime</span>
          </button>
          <a
            href="/settings/github"
            className="flex items-center gap-3 px-5 py-3 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
          >
            <Github className="w-4 h-4" />
            <span>connect github</span>
          </a>
          <a
            href="/integrations"
            className="flex items-center gap-3 px-5 py-3 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
          >
            <NotionIcon className="w-4 h-4" />
            <span>connect notion</span>
          </a>
        </div>

        {overview.error && (
          <div className="mb-4 border border-[var(--color-error)]/40 px-5 py-4 text-xs text-[var(--color-error)]">
            {overview.error}
          </div>
        )}

        <div className="mb-8">
          <div className="mb-4">
            <DbtProjectActions
              onProjectCreated={refreshProjectsSurface}
              openProjectOnComplete={false}
              showGitHubImport={false}
            />
          </div>
          <DbtProjectList
            key={projectListRefreshNonce}
            onRefresh={refreshProjectsSurface}
          />
        </div>

        {overview.loading ? (
          <div className="border border-[var(--color-border)] px-5 py-10 flex items-center justify-center gap-3 text-xs text-[var(--color-text-dim)] uppercase tracking-wider">
            <Loader2 className="w-4 h-4 animate-spin" />
            checking integrations...
          </div>
        ) : overview.notionConnected ? (
          <>
            <div className="mb-3">
              <Header
                Icon={NotionIcon}
                control={
                  <Button
                    variant="text"
                    size="xs"
                    onClick={refreshOverview}
                    disabled={overviewLoading}
                    title="Refresh Notion requests"
                  >
                    {overviewLoading ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <RefreshCw size={14} />
                    )}
                  </Button>
                }
              >
                Notion requests
              </Header>
            </div>
            <NotionConversationList
              conversations={notionConversations}
              loading={overviewLoading}
              error={overviewError}
            />
          </>
        ) : (
          <div className="border border-[var(--color-border)] px-5 py-10 text-sm text-[var(--color-text-dim)]">
            <p>Connect Notion to generate notebook-backed requests from Notion comments.</p>
            <a
              href="/integrations"
              className="inline-flex items-center gap-2 mt-4 px-4 py-2 text-[12px] text-[var(--color-bg)] bg-[var(--color-text)] hover:opacity-90 transition-all tracking-wider uppercase"
            >
              <NotionIcon className="w-3.5 h-3.5" />
              connect notion
            </a>
          </div>
        )}
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
        loading notion requests...
      </div>
    );
  }

  if (error) {
    return (
      <div className="border border-[var(--color-error)]/40 px-5 py-4 text-xs text-[var(--color-error)]">
        Could not load Notion requests: {error}
      </div>
    );
  }

  if (conversations.length === 0) {
    return (
      <div className="py-8 text-center text-muted-foreground text-sm">
        <NotionIcon className="mx-auto mb-2 h-6 w-6 opacity-40" />
        <p>No Notion requests found.</p>
        <p className="text-xs mt-1">@ SignalPilot in your Notion workspace.</p>
      </div>
    );
  }

  return (
    <div className="border border-[var(--color-border)] divide-y divide-[var(--color-border)]">
      {conversations.map((conversation) => {
        const file = conversation.notebook_path || "";
        const href = file
          ? `/projects?file=${encodeURIComponent(file)}&session_id=${encodeURIComponent(conversation.id)}`
          : `/projects?session_id=${encodeURIComponent(conversation.id)}`;
        const status = conversation.status || "saved";
        return (
          <a
            key={conversation.id}
            href={href}
            className="flex items-center gap-4 px-5 py-4 hover:bg-[var(--color-bg-hover)] transition-colors"
          >
            <div className="min-w-0 flex-1">
              <div className="text-sm text-[var(--color-text)] truncate">
                {conversation.title || "Notion request"}
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
