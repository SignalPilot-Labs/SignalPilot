"use client";

import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { Check, ExternalLink, Loader2, Share2 } from "lucide-react";
import {
  createNotebookSession,
  getNotebookSession,
  deleteNotebookSession,
  pingNotebookSession,
  getGatewayAuthToken,
  type NotebookSession,
} from "~/lib/api";
import { useToast } from "~/components/ui/toast";
import {
  NotebookProvider,
  type NotebookConfig,
} from "~/components/notebook/notebook-context";
import { PlanRequired } from "~/components/billing/plan-required";
import { buildProjectEditorHref } from "~/lib/project-editor-link";
import { useSubscription } from "~/lib/subscription-context";
import {
  GATEWAY_URL,
  IS_CLOUD_MODE,
  NOTEBOOK_PROXY_URL,
  SPA_NAVIGATE_EVENT,
  isTrailSessionId,
  resolveRuntimeMode,
  type AppState,
  type ResolvedTrail,
  type RuntimeProduct,
} from "./notebooks-page-runtime";
import { IDEHeader, NotebookLandingScreen, NotebookLoadingScreen } from "./notebooks-page-screens";
import { useNotionTrail } from "./use-notion-trail";

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

export default function NotebooksPage() {
  const { toast } = useToast();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const { isBillable, isLoaded: subLoaded } = useSubscription();
  const isExternalView = pathname?.startsWith("/notebook") ?? false;
  const [browserSearch, setBrowserSearch] = useState(() =>
    typeof window === "undefined" ? "" : window.location.search,
  );

  const gated = IS_CLOUD_MODE && subLoaded && !isBillable;

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
  const [launchStatus, setLaunchStatus] = useState(hasDeepLink ? "opening..." : "");
  const [notebookConfig, setNotebookConfig] = useState<NotebookConfig | null>(null);
  const [, setActiveNotebookSession] =
    useState<NotebookSession | null>(null);
  const [notionConnected, setNotionConnected] = useState(false);
  const [copied, setCopied] = useState(false);
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

  const {
    isNotionTrail,
    clearNotionTrailProjectState,
    rememberResolvedNotionThread,
    preserveResolvedNotionSessionInUrl,
    primeNotionTrailChrome,
    primeNotionTrailEditorState,
    resolveNotionThreadId,
    resolveTrailMetadata,
  } = useNotionTrail({ urlProject, urlFile, urlSessionId, setNotionConnected });

  useEffect(() => {
    return () => {
      if (pingRef.current) {
        clearInterval(pingRef.current);
        pingRef.current = null;
      }
    };
  }, []);

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

      // Project mode is sessionless-first: the editor and file tree mount
      // straight off the gateway workspace store with NO sandbox. The only
      // reason to look for a session here is a warm kernel from a refresh —
      // if one matches, attach to it so outputs replay; otherwise open
      // instantly and let the first Run provision compute.
      if (runtimeMode === "project") {
        let warmSessionId: string | null = null;
        try {
          const session = (await getNotebookSession()) as any;
          if (
            session?.status === "running" &&
            session.id &&
            session.notebook_url &&
            (session.project_id || "") === urlProject &&
            (session.branch || "main") === activeBranch
          ) {
            warmSessionId = session.id;
          }
        } catch (err) {
          console.warn("Failed to check existing session:", err);
        }
        if (cancelled) return;
        const config = await buildConfig(warmSessionId ?? "", apiKey, "projects");
        if (cancelled) return;
        setNotebookConfig(config);
        setState("booting");
        if (warmSessionId) startPing(warmSessionId);
        return;
      }

      try {
        const session = await getNotebookSession() as any;
        if (!cancelled && session?.status === "running" && session.id && session.notebook_url) {
          const sessionProject = session.project_id || "";
          const sessionBranch = session.branch || "main";
          if (runtimeMode === "notion-trail") {
            const trail = await resolveTrailMetadata();
            if (
              trail &&
              sessionProject === trail.project_id &&
              sessionBranch === (trail.branch || "main")
            ) {
              const config = await buildConfig(session.id, apiKey, "notebooks", trail);
              setNotebookConfig(config);
              setState("booting");
              startPing(session.id);
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
            startPing(session.id);
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

  // Legacy eager launch — only for Notion/Slack trails and the standalone
  // (project-less) notebook surface, which still need a session up front.
  // Project notebooks NEVER pass through here: they boot sessionless and
  // provision compute lazily on first Run.
  async function launch(
    existingApiKey?: string,
    product: RuntimeProduct = runtimeMode === "project" ? "projects" : "notebooks",
  ) {
    setState("loading");
    setLaunchStatus("opening notebook...");
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
      const config = await buildConfig(session.id, apiKey, product, trail);

      setNotebookConfig(config);
      setState("booting");
      startPing(session.id);
    } catch (e) {
      toast(String(e), "error");
      setState("no-session");
    }
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

  function startPing(sessionId: string) {
    if (pingRef.current) clearInterval(pingRef.current);
    pingRef.current = setInterval(() => {
      pingNotebookSession(sessionId).catch((err) =>
        console.warn("Ping failed:", err),
      );
    }, 60_000);
  }

  async function handleShare(config: NotebookConfig) {
    const projectId = urlProject || config.project;
    const branch = urlProject ? activeBranch : config.branch;
    const file = urlFile || config.file;
    let url = window.location.href;

    if (projectId && branch && file) {
      try {
        url = new URL(
          buildProjectEditorHref({ project: projectId, branch, file }),
          window.location.origin,
        ).toString();
      } catch {
        toast("Cannot share a file outside this project", "error");
        return;
      }
    }

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

  // The following code displays the cloud paywall.
  if (gated) {
    return (
      <PlanRequired
        feature="notebooks and projects"
        description="Governed notebook workspaces backed by your connections and dbt projects."
      />
    );
  }

  // The following code displays the loading state.
  if (state === "loading") {
    return <NotebookLoadingScreen launchStatus={launchStatus} />;
  }

  // The following code displays the boot and ready states.
  if ((state === "booting" || state === "ready") && notebookConfig) {
    const effectiveNotebookConfig = getEffectiveNotebookConfig(notebookConfig);
    const bootKey = [
      effectiveNotebookConfig.product ?? "",
      effectiveNotebookConfig.sessionId,
      effectiveNotebookConfig.project ?? "",
      effectiveNotebookConfig.branch ?? "",
      effectiveNotebookConfig.kernelSessionId ?? "",
    ].join(":");
    return (
      <div className="flex flex-col h-screen bg-background text-foreground">
        <IDEHeader
          right={
            <>
              <button
                onClick={() => handleShare(effectiveNotebookConfig)}
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
                  title="Open notebook full screen"
                  aria-label="Open notebook full screen"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-muted-foreground border border-border hover:border-muted-foreground hover:text-foreground transition-all tracking-wider uppercase"
                >
                  <ExternalLink className="w-3 h-3" /> full screen
                </a>
              )}
            </>
          }
        >
          {/* No machine status here on purpose: there is no machine to
              start or stop. Kernel state lives in the editor footer. */}
          {state === "booting" && (
            <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />
          )}
        </IDEHeader>
        <div className="flex-1 min-h-0 overflow-hidden">
          <NotebookProvider key={bootKey} value={effectiveNotebookConfig}>
            <NotebookBoot key={bootKey} onReady={handleBootReady} />
          </NotebookProvider>
        </div>
      </div>
    );
  }

  // The following code displays the page without a session.
  return <NotebookLandingScreen onLaunch={() => launch(undefined, "notebooks")} />;
}
