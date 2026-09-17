"use client";

import { Database, ExternalLink, GitBranch, Loader2, Plus } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { useToast } from "~/components/ui/toast";
import {
  createWorkspaceProject,
  getGitHubInstallUrl,
  getGitHubInstallations,
  getGitHubRepos,
  importGitHubRepo,
} from "~/lib/api";
import type { GitHubInstallation, GitHubRepo } from "~/lib/types";
import { OUTLINE_BUTTON, PRIMARY_BUTTON, getErrorMessage, slugifyProjectName } from "~/components/projects/projects-overview-shared";
import { usePermissions } from "~/lib/hooks/use-permissions";

/**
 * "Create new project" / "Import from GitHub". Creating a project is
 * `projects.write`, importing a repo is `github.write`; a member holds neither
 * and sees no creation flow at all.
 */
export function WorkspaceProjectActions({
  onProjectChanged,
}: {
  onProjectChanged: () => void | Promise<void>;
}) {
  const { can } = usePermissions();
  const canCreate = can("projects.write");
  const canImport = can("github.write");
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);

  if (!canCreate && !canImport) return null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {canCreate && (
          <button
            type="button"
            className={OUTLINE_BUTTON}
            onClick={() => setShowCreate((value) => !value)}
          >
            <Plus className="h-3.5 w-3.5" />
            Create new project
          </button>
        )}
        {canImport && (
          <button
            type="button"
            className={OUTLINE_BUTTON}
            onClick={() => setShowImport((value) => !value)}
          >
            <GitBranch className="h-3.5 w-3.5" />
            Import from GitHub
          </button>
        )}
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
      const result = await importGitHubRepo({
        installation_id: selectedInstall.id,
        repo_full_name: repo.full_name,
        repo_id: repo.id,
        default_branch: repo.default_branch,
      });

      toast(
        result.created
          ? `Imported ${repo.full_name}`
          : `${repo.full_name} was already imported`,
        "success",
      );
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

export function LocalProjectForm({
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
