"use client";

import { useEffect, type Dispatch, type SetStateAction } from "react";
import { getGatewayAuthToken, resolveAnalysisTrail } from "~/lib/api";
import {
  GATEWAY_BRANCH_STORAGE_KEY,
  GATEWAY_PROJECT_STORAGE_KEY,
  GATEWAY_URL,
  KnownQueryParams,
  NOTION_THREAD_EVENT,
  NOTION_THREAD_STORAGE_PREFIX,
  isNotionTrailParams,
  isTrailSessionId,
  type ChatTraceThread,
  type NotionThreadWindow,
  type ResolvedTrail,
} from "./notebooks-page-runtime";

/**
 * Notion and Slack analysis-trail handling for the notebooks page: resolves
 * the trail's kernel session and project, and primes the URL and editor
 * localStorage so the trail opens on the right tab.
 */
export function useNotionTrail({
  urlProject,
  urlFile,
  urlSessionId,
  setNotionConnected,
}: {
  urlProject: string;
  urlFile: string;
  urlSessionId: string;
  setNotionConnected: Dispatch<SetStateAction<boolean>>;
}) {
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

  async function fetchNotionTraceThreads() {
    const token = await getGatewayAuthToken();
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;

    return fetch(`${GATEWAY_URL}/api/notebook-chat/traces/threads`, {
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

  return {
    isNotionTrail,
    clearNotionTrailProjectState,
    rememberResolvedNotionThread,
    preserveResolvedNotionSessionInUrl,
    primeNotionTrailChrome,
    primeNotionTrailEditorState,
    resolveNotionThreadId,
    resolveTrailMetadata,
  };
}
