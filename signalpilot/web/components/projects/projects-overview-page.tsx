"use client";

import {
  useRouter,
} from "next/navigation";
import { Code, Database, FolderPlus, Github, Loader2, RefreshCw, type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useState, type ComponentType, type ReactNode } from "react";

import { NotionIcon } from "~/components/branding/notion-icon";
import { useToast } from "~/components/ui/toast";
import {
  createNotebookSession,
  getGatewayAuthToken,
  getGitHubInstallations,
  getNotionOAuthInstallations,
  getProjects,
  getWorkspaceProjects,
} from "~/lib/api";
import type { WorkspaceProjectInfo } from "~/lib/types";
import { ICON_BUTTON, type NotionConversation, getErrorMessage } from "~/components/projects/projects-overview-shared";
import { LocalProjectForm, WorkspaceProjectActions } from "~/components/projects/project-create-forms";
import { NotionConversationList, ProjectGrid } from "~/components/projects/project-grid";
import { usePermissions } from "~/lib/hooks/use-permissions";

const GATEWAY_URL =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3300";
const GATEWAY_PROJECT_STORAGE_KEY = "sp:gateway-project-id";
const GATEWAY_BRANCH_STORAGE_KEY = "sp:gateway-branch-id";
const DBT_PROJECT_DIR_STORAGE_KEY = "sp:dbt-project-dir";

type OverviewState = {
  loading: boolean;
  projectCount: number;
  githubConnected: boolean;
  notionConnected: boolean;
  error: string | null;
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

function isTrailSessionId(sessionId?: string): sessionId is string {
  return Boolean(
    sessionId?.startsWith("session-notion-") ||
      sessionId?.startsWith("session-slack-"),
  );
}

function hasUsableNotionInstallation(
  installations: Array<{ status?: string; config?: { enabled?: boolean } | null }>,
): boolean {
  return installations.some(
    (installation) =>
      installation.status !== "disconnected" &&
      installation.config?.enabled === true,
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

function clearRuntimeCaches() {
  window.localStorage.removeItem("sp:file-tree-cache");
  window.localStorage.removeItem("sp:file-tree-open-state");
}

function setProjectRuntimeStorage(projectId: string, branch: string) {
  window.localStorage.setItem(GATEWAY_PROJECT_STORAGE_KEY, projectId);
  window.localStorage.setItem(GATEWAY_BRANCH_STORAGE_KEY, branch);
  window.localStorage.removeItem(DBT_PROJECT_DIR_STORAGE_KEY);
  clearRuntimeCaches();
}

function clearProjectRuntimeStorage() {
  window.localStorage.removeItem(GATEWAY_PROJECT_STORAGE_KEY);
  window.localStorage.removeItem(GATEWAY_BRANCH_STORAGE_KEY);
  clearRuntimeCaches();
}

export default function ProjectsOverviewPage() {
  const { can } = usePermissions();
  const canCreateProject = can("projects.write");
  const { toast } = useToast();
  const router = useRouter();
  const [overview, setOverview] = useState<OverviewState>({
    loading: true,
    projectCount: 0,
    githubConnected: false,
    notionConnected: false,
    error: null,
  });
  const [projects, setProjects] = useState<WorkspaceProjectInfo[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [notionConversations, setNotionConversations] = useState<
    NotionConversation[]
  >([]);
  const [notionLoading, setNotionLoading] = useState(false);
  const [notionError, setNotionError] = useState<string | null>(null);
  const [launchingNotebook, setLaunchingNotebook] = useState(false);
  const [showLocalImport, setShowLocalImport] = useState(false);
  const [openingLocalProject, setOpeningLocalProject] = useState(false);

  const loadNotionConversations = useCallback(async (notionConnected: boolean) => {
    if (!notionConnected) {
      setNotionError(null);
      setNotionConversations([]);
      return;
    }

    setNotionLoading(true);
    setNotionError(null);
    try {
      const token = await getGatewayAuthToken();
      const headers: Record<string, string> = {};
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }
      const response = await fetch(`${GATEWAY_URL}/api/chat/traces/threads`, {
        headers,
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = (await response.json()) as { threads?: ChatTraceThread[] };
      setNotionConversations(
        (data.threads ?? [])
          .map(toNotionConversation)
          .filter(
            (conversation) =>
              conversation.source === "notion" ||
              isTrailSessionId(conversation.id),
          ),
      );
    } catch (error) {
      setNotionError(getErrorMessage(error));
      setNotionConversations([]);
    } finally {
      setNotionLoading(false);
    }
  }, []);

  const loadOverview = useCallback(async () => {
    setOverview((prev) => ({ ...prev, loading: true, error: null }));
    setProjectsLoading(true);

    const [projectsResult, githubResult, notionResult] =
      await Promise.allSettled([
        getWorkspaceProjects("active"),
        getGitHubInstallations(),
        getNotionOAuthInstallations(),
      ]);

    let projectCount = 0;
    if (projectsResult.status === "fulfilled") {
      setProjects(projectsResult.value.projects ?? []);
      projectCount = projectsResult.value.total;
    } else {
      setProjects([]);
      try {
        projectCount = (await getProjects()).length;
      } catch {
        projectCount = 0;
      }
    }
    setProjectsLoading(false);

    const nextOverview: OverviewState = {
      loading: false,
      projectCount,
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
    await loadNotionConversations(nextOverview.notionConnected);
  }, [loadNotionConversations]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  const openNotebookRuntime = useCallback(async () => {
    setLaunchingNotebook(true);
    try {
      clearProjectRuntimeStorage();
      window.localStorage.removeItem(DBT_PROJECT_DIR_STORAGE_KEY);
      const session = await createNotebookSession({ project_id: null });
      if (!session.id) {
        throw new Error("Session created but no ID returned");
      }
      const params = new URLSearchParams();
      params.set("session_id", session.id);
      router.push(`/projects?${params.toString()}`);
    } catch (error) {
      toast(getErrorMessage(error), "error");
      setLaunchingNotebook(false);
    }
  }, [router, toast]);

  const openProject = useCallback((project: WorkspaceProjectInfo) => {
    const branch = project.default_branch || "main";
    setProjectRuntimeStorage(project.id, branch);
    const params = new URLSearchParams();
    params.set("project", project.id);
    params.set("branch", branch);
    params.set("file", "__new__project");
    router.push(`/projects?${params.toString()}`);
  }, [router]);

  const openLocalProject = useCallback(
    async (projectPath: string) => {
      const trimmed = projectPath.trim();
      if (!trimmed) {
        return;
      }
      setOpeningLocalProject(true);
      try {
        clearProjectRuntimeStorage();
        window.localStorage.setItem(
          DBT_PROJECT_DIR_STORAGE_KEY,
          JSON.stringify(trimmed),
        );
        const session = await createNotebookSession({ project_id: null });
        if (!session.id) {
          throw new Error("Session created but no ID returned");
        }
        const params = new URLSearchParams();
        params.set("file", "__new__project");
        params.set("session_id", session.id);
        router.push(`/projects?${params.toString()}`);
      } catch (error) {
        toast(getErrorMessage(error), "error");
        setOpeningLocalProject(false);
      }
    },
    [router, toast],
  );

  return (
    <div className="animate-fade-in p-8">
      <div className="mx-auto mt-16 max-w-6xl">
        <div className="mb-6 flex items-center gap-3">
          <Code className="h-6 w-6 text-[var(--color-text)]" />
          <h1 className="text-lg font-bold uppercase tracking-wider text-[var(--color-text)]">
            SignalPilot IDE
          </h1>
        </div>

        <div className="mb-8 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={openNotebookRuntime}
            disabled={launchingNotebook}
            className="inline-flex items-center gap-3 bg-[var(--color-text)] px-5 py-3 text-xs font-medium uppercase tracking-wider text-[var(--color-bg)] transition-all hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {launchingNotebook ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Code className="h-4 w-4" />
            )}
            <span>open notebook runtime</span>
          </button>
          <a
            href="/settings/github"
            className="inline-flex items-center gap-3 border border-[var(--color-border)] px-5 py-3 text-xs uppercase tracking-wider text-[var(--color-text-dim)] transition-all hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)]"
          >
            <Github className="h-4 w-4" />
            <span>connect github</span>
          </a>
          <a
            href="/integrations"
            className="inline-flex items-center gap-3 border border-[var(--color-border)] px-5 py-3 text-xs uppercase tracking-wider text-[var(--color-text-dim)] transition-all hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)]"
          >
            <NotionIcon className="h-4 w-4" />
            <span>connect notion</span>
          </a>
        </div>

        {overview.error && (
          <div className="mb-4 border border-[var(--color-error)]/40 px-5 py-4 text-xs text-[var(--color-error)]">
            {overview.error}
          </div>
        )}

        <div className="mb-8 space-y-4">
          <WorkspaceProjectActions onProjectChanged={loadOverview} />

          <div className="space-y-3">
            <SectionHeader
              Icon={Database}
              control={
                <div className="flex items-center gap-1">
                  {canCreateProject && (
                    <button
                      type="button"
                      className={ICON_BUTTON}
                      onClick={() => setShowLocalImport((value) => !value)}
                      title="Import local project"
                    >
                      <FolderPlus className="h-3.5 w-3.5" />
                    </button>
                  )}
                  <button
                    type="button"
                    className={ICON_BUTTON}
                    onClick={() => void loadOverview()}
                    disabled={projectsLoading}
                    title="Refresh projects"
                  >
                    {projectsLoading ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3.5 w-3.5" />
                    )}
                  </button>
                </div>
              }
            >
              Projects
            </SectionHeader>

            {showLocalImport && (
              <LocalProjectForm
                loading={openingLocalProject}
                onOpen={openLocalProject}
                onCancel={() => setShowLocalImport(false)}
              />
            )}

            <ProjectGrid
              projects={projects}
              loading={projectsLoading}
              projectCount={overview.projectCount}
              onProjectClick={openProject}
              onProjectSettings={(project) =>
                router.push(`/projects/${encodeURIComponent(project.id)}/settings`)
              }
              onProjectDeleted={loadOverview}
            />
          </div>
        </div>

        {overview.loading ? (
          <div className="flex items-center justify-center gap-3 border border-[var(--color-border)] px-5 py-10 text-xs uppercase tracking-wider text-[var(--color-text-dim)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            checking integrations...
          </div>
        ) : overview.notionConnected ? (
          <>
            <div className="mb-3">
              <SectionHeader
                Icon={NotionIcon}
                control={
                  <button
                    type="button"
                    className={ICON_BUTTON}
                    onClick={() =>
                      void loadNotionConversations(overview.notionConnected)
                    }
                    disabled={notionLoading}
                    title="Refresh Notion requests"
                  >
                    {notionLoading ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3.5 w-3.5" />
                    )}
                  </button>
                }
              >
                Notion requests
              </SectionHeader>
            </div>
            <NotionConversationList
              conversations={notionConversations}
              loading={notionLoading}
              error={notionError}
              onOpen={(href) => router.push(href)}
            />
          </>
        ) : (
          <div className="border border-[var(--color-border)] px-5 py-10 text-sm text-[var(--color-text-dim)]">
            <p>
              Connect Notion to generate notebook-backed requests from Notion
              comments.
            </p>
            <a
              href="/integrations"
              className="mt-4 inline-flex items-center gap-2 bg-[var(--color-text)] px-4 py-2 text-[12px] uppercase tracking-wider text-[var(--color-bg)] transition-all hover:opacity-90"
            >
              <NotionIcon className="h-3.5 w-3.5" />
              connect notion
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

function SectionHeader({
  Icon,
  control,
  children,
}: {
  Icon: LucideIcon | ComponentType<{ className?: string }>;
  control?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <h2 className="flex select-none items-center gap-2 text-[11px] font-bold uppercase tracking-[0.15em] text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {children}
      </h2>
      {control}
    </div>
  );
}
