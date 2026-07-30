"use client";

import {
  useRouter,
} from "next/navigation";
import {
  AlertTriangle,
  Cloud,
  Code,
  Database,
  ExternalLink,
  FolderPlus,
  GitBranch,
  Github,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type FormEvent,
  type ReactNode,
} from "react";

import { NotionIcon } from "~/components/branding/notion-icon";
import { useToast } from "~/components/ui/toast";
import {
  createNotebookSession,
  createWorkspaceProject,
  deleteWorkspaceProject,
  getGatewayAuthToken,
  getGitHubInstallUrl,
  getGitHubInstallations,
  getGitHubRepos,
  getNotionOAuthInstallations,
  getProjects,
  getWorkspaceProjects,
  linkGitHubRepo,
  request,
} from "~/lib/api";
import type {
  GitHubInstallation,
  GitHubRepo,
  WorkspaceProjectInfo,
} from "~/lib/types";

const GATEWAY_URL =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3300";
const GATEWAY_PROJECT_STORAGE_KEY = "sp:gateway-project-id";
const GATEWAY_BRANCH_STORAGE_KEY = "sp:gateway-branch-id";
const DBT_PROJECT_DIR_STORAGE_KEY = "sp:dbt-project-dir";

const OUTLINE_BUTTON =
  "inline-flex items-center justify-center gap-2 border border-[var(--color-border)] px-4 py-2 text-xs uppercase tracking-wider text-[var(--color-text-dim)] transition-all hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] disabled:cursor-not-allowed disabled:opacity-50";
const PRIMARY_BUTTON =
  "inline-flex items-center justify-center gap-2 bg-[var(--color-text)] px-4 py-2 text-xs uppercase tracking-wider text-[var(--color-bg)] transition-all hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60";
const ICON_BUTTON =
  "inline-flex h-8 w-8 items-center justify-center border border-transparent text-[var(--color-text-dim)] transition-colors hover:border-[var(--color-border)] hover:text-[var(--color-text)] disabled:cursor-not-allowed disabled:opacity-50";

type OverviewState = {
  loading: boolean;
  projectCount: number;
  githubConnected: boolean;
  notionConnected: boolean;
  error: string | null;
};

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

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

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

function slugifyProjectName(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "-");
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${Math.round(value / 1024)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatRelativeTime(value?: number | null): string {
  if (!value) {
    return "";
  }
  const diffMs = Date.now() - value * 1000;
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diffMs < minute) {
    return "just now";
  }
  if (diffMs < hour) {
    return `${Math.floor(diffMs / minute)}m ago`;
  }
  if (diffMs < day) {
    return `${Math.floor(diffMs / hour)}h ago`;
  }
  if (diffMs < 30 * day) {
    return `${Math.floor(diffMs / day)}d ago`;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(new Date(value * 1000));
}

function formatConversationTime(value?: number): string {
  if (!value) {
    return "";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value * 1000));
}

export default function ProjectsOverviewPage() {
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
                  <button
                    type="button"
                    className={ICON_BUTTON}
                    onClick={() => setShowLocalImport((value) => !value)}
                    title="Import local project"
                  >
                    <FolderPlus className="h-3.5 w-3.5" />
                  </button>
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

function WorkspaceProjectActions({
  onProjectChanged,
}: {
  onProjectChanged: () => void | Promise<void>;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={OUTLINE_BUTTON}
          onClick={() => setShowCreate((value) => !value)}
        >
          <Plus className="h-3.5 w-3.5" />
          Create new project
        </button>
        <button
          type="button"
          className={OUTLINE_BUTTON}
          onClick={() => setShowImport((value) => !value)}
        >
          <GitBranch className="h-3.5 w-3.5" />
          Import from GitHub
        </button>
      </div>

      {showCreate && (
        <CreateProjectForm
          onClose={() => setShowCreate(false)}
          onCreated={onProjectChanged}
        />
      )}
      {showImport && (
        <GitHubImportForm
          onClose={() => setShowImport(false)}
          onImported={onProjectChanged}
        />
      )}
    </div>
  );
}

function CreateProjectForm({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void | Promise<void>;
}) {
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [adapter, setAdapter] = useState("duckdb");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      toast("Project name is required", "error");
      return;
    }
    const slug = slugifyProjectName(trimmed);
    if (!slug) {
      toast("Project name needs at least one letter or number", "error");
      return;
    }

    setLoading(true);
    try {
      await createWorkspaceProject({
        name: slug,
        display_name: trimmed,
        description: `${trimmed} dbt project (${adapter})`,
        source: "managed",
        tags: ["dbt", adapter],
      });
      toast(`Created ${trimmed}`, "success");
      await onCreated();
      onClose();
    } catch (error) {
      toast(getErrorMessage(error), "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-3 rounded-lg border border-[var(--color-border)] bg-muted/30 p-4"
    >
      <div className="flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
        <Database className="h-3.5 w-3.5" />
        Create new dbt project
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1">
          <span className="block text-xs font-medium text-[var(--color-text-dim)]">
            Project name
          </span>
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-1.5 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-text-dim)]"
            placeholder="my_dbt_project"
            autoFocus
          />
        </label>
        <label className="space-y-1">
          <span className="block text-xs font-medium text-[var(--color-text-dim)]">
            Adapter
          </span>
          <select
            value={adapter}
            onChange={(event) => setAdapter(event.target.value)}
            className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-1.5 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-text-dim)]"
          >
            <option value="duckdb">DuckDB</option>
            <option value="postgres">PostgreSQL</option>
            <option value="snowflake">Snowflake</option>
            <option value="bigquery">BigQuery</option>
            <option value="redshift">Redshift</option>
          </select>
        </label>
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" className={OUTLINE_BUTTON} onClick={onClose}>
          Cancel
        </button>
        <button type="submit" className={PRIMARY_BUTTON} disabled={loading}>
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Create
        </button>
      </div>
    </form>
  );
}

function GitHubImportForm({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: () => void | Promise<void>;
}) {
  const { toast } = useToast();
  const [installations, setInstallations] = useState<GitHubInstallation[]>([]);
  const [repos, setRepos] = useState<GitHubRepo[]>([]);
  const [loadingInstallations, setLoadingInstallations] = useState(true);
  const [loadingRepos, setLoadingRepos] = useState(false);
  const [selectedInstall, setSelectedInstall] =
    useState<GitHubInstallation | null>(null);
  const [importingRepo, setImportingRepo] = useState<string | null>(null);
  const [connectingGitHub, setConnectingGitHub] = useState(false);

  const loadInstallations = useCallback(async () => {
    setLoadingInstallations(true);
    try {
      const data = await getGitHubInstallations();
      setInstallations(data);
      if (data.length >= 1) {
        setSelectedInstall(data[0]);
      }
    } catch (error) {
      toast(getErrorMessage(error), "error");
      setInstallations([]);
    } finally {
      setLoadingInstallations(false);
    }
  }, [toast]);

  useEffect(() => {
    void loadInstallations();
  }, [loadInstallations]);

  useEffect(() => {
    if (!selectedInstall) {
      setRepos([]);
      return;
    }

    let cancelled = false;
    setLoadingRepos(true);
    getGitHubRepos(selectedInstall.id)
      .then((nextRepos) => {
        if (!cancelled) {
          setRepos(nextRepos);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRepos([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingRepos(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedInstall]);

  const connectGitHub = async () => {
    setConnectingGitHub(true);
    try {
      const { install_url } = await getGitHubInstallUrl();
      window.location.href = install_url;
    } catch (error) {
      toast(getErrorMessage(error), "error");
      setConnectingGitHub(false);
    }
  };

  const importRepo = async (repo: GitHubRepo) => {
    if (!selectedInstall) {
      return;
    }

    setImportingRepo(repo.full_name);
    try {
      const project = await createWorkspaceProject({
        name: repo.name,
        display_name: repo.name,
        description: repo.description || "",
        source: "github",
        tags: ["github"],
      });

      await linkGitHubRepo({
        project_id: project.id,
        installation_id: selectedInstall.id,
        repo_full_name: repo.full_name,
        repo_id: repo.id,
        default_branch: repo.default_branch,
      });

      toast("Mirroring repository from GitHub...", "info");
      try {
        await request<unknown>(`/api/github/sync/${project.id}`, {
          method: "POST",
        });
      } catch (error) {
        console.warn("[Projects] Gateway GitHub sync failed:", error);
      }

      toast(`Imported ${repo.full_name}`, "success");
      await onImported();
      onClose();
    } catch (error) {
      toast(getErrorMessage(error), "error");
    } finally {
      setImportingRepo(null);
    }
  };

  return (
    <div className="space-y-3 rounded-lg border border-[var(--color-border)] bg-muted/30 p-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
        <GitBranch className="h-3.5 w-3.5" />
        Import from GitHub
      </div>

      {loadingInstallations ? (
        <div className="flex items-center justify-center gap-2 py-6 text-xs text-[var(--color-text-dim)]">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading GitHub connections...
        </div>
      ) : installations.length === 0 ? (
        <div className="space-y-3 py-4 text-center">
          <p className="text-sm text-[var(--color-text-dim)]">
            No GitHub account connected.
          </p>
          <button
            type="button"
            onClick={connectGitHub}
            disabled={connectingGitHub}
            className={OUTLINE_BUTTON}
          >
            {connectingGitHub && (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            )}
            Connect GitHub
            <ExternalLink className="h-3 w-3" />
          </button>
        </div>
      ) : (
        <>
          {installations.length > 1 && (
            <div className="flex flex-wrap gap-2">
              {installations.map((installation) => (
                <button
                  key={installation.id}
                  type="button"
                  className={
                    selectedInstall?.id === installation.id
                      ? PRIMARY_BUTTON
                      : OUTLINE_BUTTON
                  }
                  onClick={() => setSelectedInstall(installation)}
                >
                  {installation.github_account_login}
                </button>
              ))}
            </div>
          )}

          {loadingRepos ? (
            <div className="flex items-center justify-center gap-2 py-4 text-xs text-[var(--color-text-dim)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Loading repositories...
            </div>
          ) : repos.length === 0 ? (
            <div className="py-4 text-center text-sm text-[var(--color-text-dim)]">
              <p>No repositories found.</p>
              <button
                type="button"
                onClick={connectGitHub}
                disabled={connectingGitHub}
                className="mt-2 inline-flex items-center gap-1.5 text-xs text-[var(--color-text)] hover:underline disabled:cursor-not-allowed disabled:opacity-60"
              >
                {connectingGitHub && (
                  <Loader2 className="h-3 w-3 animate-spin" />
                )}
                Add more repositories
                <ExternalLink className="h-3 w-3" />
              </button>
            </div>
          ) : (
            <div className="max-h-[240px] space-y-1 overflow-y-auto">
              {repos.map((repo) => (
                <div
                  key={repo.id}
                  className="flex items-center gap-3 rounded-md border border-[var(--color-border)] px-3 py-2 transition-colors hover:border-[var(--color-text-dim)] hover:bg-muted/30"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-[var(--color-text)]">
                      {repo.full_name}
                    </div>
                    {repo.description && (
                      <div className="truncate text-xs text-[var(--color-text-dim)]">
                        {repo.description}
                      </div>
                    )}
                    <div className="mt-0.5 flex items-center gap-2 text-[10px] text-[var(--color-text-dim)]">
                      <span>{repo.default_branch}</span>
                      {repo.private && (
                        <span className="border border-[var(--color-border)] px-1">
                          private
                        </span>
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    className={OUTLINE_BUTTON}
                    onClick={() => void importRepo(repo)}
                    disabled={importingRepo !== null}
                  >
                    {importingRepo === repo.full_name && (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    )}
                    Import
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="flex items-center justify-between border-t border-[var(--color-border)]/50 pt-2">
            <button
              type="button"
              className={OUTLINE_BUTTON}
              onClick={connectGitHub}
              disabled={connectingGitHub}
            >
              {connectingGitHub ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Plus className="h-3.5 w-3.5" />
              )}
              Add Repository
              <ExternalLink className="h-3 w-3 opacity-60" />
            </button>
            <button type="button" className={OUTLINE_BUTTON} onClick={onClose}>
              Cancel
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function LocalProjectForm({
  loading,
  onOpen,
  onCancel,
}: {
  loading: boolean;
  onOpen: (projectPath: string) => void | Promise<void>;
  onCancel: () => void;
}) {
  const [projectPath, setProjectPath] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    await onOpen(projectPath);
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-2 px-1 sm:flex-row sm:items-center"
    >
      <input
        ref={inputRef}
        type="text"
        value={projectPath}
        onChange={(event) => setProjectPath(event.target.value)}
        placeholder="Paste path to local dbt project folder..."
        className="min-w-0 flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-1.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-dim)]/60 outline-none focus:border-[var(--color-text-dim)]"
      />
      <div className="flex gap-2">
        <button
          type="submit"
          className={PRIMARY_BUTTON}
          disabled={!projectPath.trim() || loading}
        >
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Open
        </button>
        <button type="button" className={OUTLINE_BUTTON} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function ProjectGrid({
  projects,
  loading,
  projectCount,
  onProjectClick,
  onProjectDeleted,
}: {
  projects: WorkspaceProjectInfo[];
  loading: boolean;
  projectCount: number;
  onProjectClick: (project: WorkspaceProjectInfo) => void;
  onProjectDeleted: () => void | Promise<void>;
}) {
  if (loading && projects.length === 0) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-sm text-[var(--color-text-dim)]">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading projects...
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-[var(--color-text-dim)]">
        <Cloud className="mx-auto mb-2 h-6 w-6 opacity-40" />
        <p>No projects found.</p>
        {projectCount > 0 && (
          <p className="mt-1 text-xs">
            Workspace projects could not be listed, but legacy projects were
            detected.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {projects.map((project) => (
        <ProjectCard
          key={project.id}
          project={project}
          onClick={onProjectClick}
          onDeleted={onProjectDeleted}
        />
      ))}
    </div>
  );
}

function ProjectCard({
  project,
  onClick,
  onDeleted,
}: {
  project: WorkspaceProjectInfo;
  onClick: (project: WorkspaceProjectInfo) => void;
  onDeleted: () => void | Promise<void>;
}) {
  const [showDelete, setShowDelete] = useState(false);
  const tags = project.tags ?? [];
  const projectName = project.display_name || project.name;
  const details = [
    project.file_count > 0 ? `${project.file_count} files` : "",
    formatBytes(project.total_bytes),
    formatRelativeTime(project.updated_at),
  ].filter(Boolean);

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        className="group relative w-full rounded-lg border border-[var(--color-border)] p-4 text-left transition-all duration-150 hover:border-[var(--color-text-dim)] hover:bg-muted/50"
        onClick={() => onClick(project)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onClick(project);
          }
        }}
      >
        <div className="flex items-start gap-3">
          <div className="mt-0.5 rounded-md bg-primary/10 p-2 text-primary">
            <Cloud className="h-[18px] w-[18px]" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-[var(--color-text)]">
              {projectName}
            </div>
            {project.description && (
              <div className="mt-0.5 truncate text-xs text-[var(--color-text-dim)]">
                {project.description}
              </div>
            )}
            {project.connection_name && (
              <div className="mt-0.5 text-xs text-[var(--color-text-dim)]">
                <Database className="mr-1 inline h-2.5 w-2.5" />
                {project.connection_name}
              </div>
            )}
            {details.length > 0 && (
              <div className="mt-1.5 flex items-center gap-3 text-[10px] text-[var(--color-text-dim)]">
                {details.map((detail) => (
                  <span key={detail}>{detail}</span>
                ))}
              </div>
            )}
            {tags.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-[var(--color-text-dim)]"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
        <button
          type="button"
          className="absolute right-2 top-2 rounded-md p-1.5 text-[var(--color-text-dim)] opacity-0 transition-opacity hover:bg-[var(--color-error)]/10 hover:text-[var(--color-error)] group-hover:opacity-100"
          onClick={(event) => {
            event.stopPropagation();
            setShowDelete(true);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              event.stopPropagation();
              setShowDelete(true);
            }
          }}
          aria-label={`Delete ${projectName}`}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {showDelete && (
        <DeleteProjectModal
          project={project}
          onClose={() => setShowDelete(false)}
          onDeleted={async () => {
            setShowDelete(false);
            await onDeleted();
          }}
        />
      )}
    </>
  );
}

function DeleteProjectModal({
  project,
  onClose,
  onDeleted,
}: {
  project: WorkspaceProjectInfo;
  onClose: () => void;
  onDeleted: () => void | Promise<void>;
}) {
  const { toast } = useToast();
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const projectName = project.display_name || project.name;
  const confirmPhrase = `delete ${projectName}`;
  const isConfirmed =
    confirmText.trim().toLowerCase() === confirmPhrase.toLowerCase();

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const deleteProject = async () => {
    if (!isConfirmed) {
      return;
    }
    setDeleting(true);
    setError("");
    try {
      await deleteWorkspaceProject(project.id);
      toast(`${projectName} has been deleted`, "success");
      await onDeleted();
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="mx-4 w-full max-w-md overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-[var(--color-error)]/20 bg-[var(--color-error)]/5 px-5 py-4">
          <div className="rounded-full bg-[var(--color-error)]/10 p-2">
            <AlertTriangle className="h-5 w-5 text-[var(--color-error)]" />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-[var(--color-text)]">
              Delete Project
            </h3>
            <p className="text-xs text-[var(--color-text-dim)]">
              This action cannot be undone
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className={ICON_BUTTON}
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 px-5 py-4">
          <div className="text-sm text-[var(--color-text-dim)]">
            This will permanently delete{" "}
            <span className="font-semibold text-[var(--color-text)]">
              {projectName}
            </span>
            , including all branches, files, and commit history.
          </div>

          <label className="block space-y-2">
            <span className="block text-xs font-medium text-[var(--color-text-dim)]">
              To confirm, type{" "}
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[var(--color-text)]">
                {confirmPhrase}
              </span>
            </span>
            <input
              ref={inputRef}
              type="text"
              value={confirmText}
              onChange={(event) => setConfirmText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && isConfirmed) {
                  void deleteProject();
                }
              }}
              placeholder={confirmPhrase}
              className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 font-mono text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-text-dim)]"
              autoComplete="off"
              spellCheck={false}
            />
          </label>

          {error && (
            <div className="rounded-md border border-[var(--color-error)]/20 bg-[var(--color-error)]/5 px-3 py-2 text-xs text-[var(--color-error)]">
              {error}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-[var(--color-border)] bg-muted/30 px-5 py-3">
          <button type="button" className={OUTLINE_BUTTON} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="inline-flex items-center justify-center gap-2 border border-[var(--color-error)] px-4 py-2 text-xs uppercase tracking-wider text-[var(--color-error)] transition-all hover:bg-[var(--color-error)]/10 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => void deleteProject()}
            disabled={!isConfirmed || deleting}
          >
            {deleting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
            Delete project
          </button>
        </div>
      </div>
    </div>
  );
}

function NotionConversationList({
  conversations,
  loading,
  error,
  onOpen,
}: {
  conversations: NotionConversation[];
  loading: boolean;
  error: string | null;
  onOpen: (href: string) => void;
}) {
  if (loading && conversations.length === 0) {
    return (
      <div className="flex items-center justify-center gap-3 border border-[var(--color-border)] px-5 py-10 text-xs uppercase tracking-wider text-[var(--color-text-dim)]">
        <Loader2 className="h-4 w-4 animate-spin" />
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
      <div className="py-8 text-center text-sm text-[var(--color-text-dim)]">
        <NotionIcon className="mx-auto mb-2 h-6 w-6 opacity-40" />
        <p>No Notion requests found.</p>
        <p className="mt-1 text-xs">@ SignalPilot in your Notion workspace.</p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-[var(--color-border)] border border-[var(--color-border)]">
      {conversations.map((conversation) => {
        const file = conversation.notebook_path || "";
        const params = new URLSearchParams();
        if (file) {
          params.set("file", file);
        }
        params.set("session_id", conversation.id);
        const href = `/projects?${params.toString()}`;
        const status = conversation.status || "saved";
        return (
          <a
            key={conversation.id}
            href={href}
            onClick={(event) => {
              event.preventDefault();
              onOpen(href);
            }}
            className="flex items-center gap-4 px-5 py-4 transition-colors hover:bg-[var(--color-bg-hover)]"
          >
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-[var(--color-text)]">
                {conversation.title || "Notion request"}
              </div>
              <div className="mt-1 truncate font-mono text-[11px] text-[var(--color-text-dim)]">
                {file || conversation.id}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <span className="border border-[var(--color-border)] px-2 py-1 text-[10px] uppercase tracking-wider text-[var(--color-text-dim)]">
                {status}
              </span>
              <span className="text-[11px] text-[var(--color-text-dim)]">
                {formatConversationTime(conversation.updated_at)}
              </span>
              <ExternalLink className="h-4 w-4 text-[var(--color-text-dim)]" />
            </div>
          </a>
        );
      })}
    </div>
  );
}
