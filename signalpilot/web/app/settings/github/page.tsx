"use client";

import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  GitBranch,
  Loader2,
  Plug,
  Unplug,
  Link as LinkIcon,
  Unlink,
} from "lucide-react";
import {
  getGitHubInstallUrl,
  getGitHubInstallations,
  deleteGitHubInstallation,
  getGitHubRepos,
  getGitHubRepoLinks,
  getGitHubImportStatus,
  importGitHubRepo,
  deleteWorkspaceProject,
  getWorkspaceProjects,
} from "~/lib/api";
import type {
  GitHubInstallation,
  GitHubRepo,
  GitHubRepoLink,
  WorkspaceProjectInfo,
} from "~/lib/types";
import { PageHeader, TerminalBar } from "~/components/ui/page-header";
import { StatusDot } from "~/components/ui/data-viz";
import { useToast } from "~/components/ui/toast";

export default function GitHubConnectionsPage() {
  const { toast } = useToast();
  const searchParams = useSearchParams();
  const router = useRouter();

  const [installations, setInstallations] = useState<GitHubInstallation[]>([]);
  const [repoLinks, setRepoLinks] = useState<GitHubRepoLink[]>([]);
  const [projects, setProjects] = useState<WorkspaceProjectInfo[]>([]);
  const [loading, setLoading] = useState(true);

  // Repo picker state
  const [pickerInstallId, setPickerInstallId] = useState<string | null>(null);
  const [pickerRepos, setPickerRepos] = useState<GitHubRepo[]>([]);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [linkingRepo, setLinkingRepo] = useState<string | null>(null);
  const [linkStage, setLinkStage] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [confirmDeleteLink, setConfirmDeleteLink] = useState<string | null>(null);
  const [deletingLink, setDeletingLink] = useState<string | null>(null);

  const githubError = searchParams.get("error");
  const githubErrorMessage =
    githubError === "oauth_state_invalid"
      ? "GitHub connection expired. Please try again."
      : githubError === "github_app_not_configured"
        ? "GitHub App is not configured for this workspace."
        : githubError
          ? "GitHub connection failed. Please try again."
          : null;

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [installs, links, projs] = await Promise.all([
        getGitHubInstallations(),
        getGitHubRepoLinks(),
        getWorkspaceProjects("active").then((r) => r.projects),
      ]);
      setInstallations(installs);
      setRepoLinks(links);
      setProjects(projs);
    } catch {
      // GitHub not configured — show empty state
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
    if (searchParams.get("installed") === "true") {
      toast("GitHub App connected successfully", "success");
      const returnTo = sessionStorage.getItem("sp_github_return_to");
      if (returnTo === "/evals") {
        sessionStorage.removeItem("sp_github_return_to");
        router.replace(returnTo);
      }
    }
    if (githubErrorMessage) {
      toast(githubErrorMessage, "error");
    }
  }, [githubErrorMessage, refresh, router, searchParams, toast]);

  async function handleConnectGitHub() {
    setConnecting(true);
    try {
      const { install_url } = await getGitHubInstallUrl();
      window.location.href = install_url;
    } catch (e) {
      toast(String(e), "error");
      setConnecting(false);
    }
  }

  async function handleDisconnect(id: string) {
    try {
      await deleteGitHubInstallation(id);
      toast("GitHub account disconnected", "success");
      refresh();
    } catch (e) {
      toast(String(e), "error");
    }
  }

  async function openRepoPicker(installId: string) {
    setPickerInstallId(installId);
    setPickerLoading(true);
    try {
      const repos = await getGitHubRepos(installId);
      setPickerRepos(repos);
    } catch (e) {
      toast(`Failed to load repos: ${e}`, "error");
      setPickerRepos([]);
    }
    setPickerLoading(false);
  }

  function describeStage(s: { stage: string; done?: number; total?: number }): string {
    switch (s.stage) {
      case "creating-project":
        return "creating project…";
      case "cloning":
        return "cloning repository…";
      case "importing-files":
        return s.total
          ? `importing files ${s.done ?? 0}/${s.total}…`
          : "importing files…";
      case "done":
        return "finishing…";
      default:
        return "linking…";
    }
  }

  async function handleLinkRepo(repo: GitHubRepo) {
    if (!pickerInstallId || linkingRepo) return;
    setLinkingRepo(repo.full_name);
    setLinkStage("linking…");
    const poll = setInterval(() => {
      getGitHubImportStatus(repo.full_name)
        .then((s) => setLinkStage(describeStage(s)))
        .catch(() => {});
    }, 1000);
    try {
      const result = await importGitHubRepo({
        installation_id: pickerInstallId,
        repo_full_name: repo.full_name,
        repo_id: repo.id,
        default_branch: repo.default_branch,
      });
      toast(
        result.created
          ? `Linked ${repo.full_name} — project "${result.project.display_name}" created`
          : `${repo.full_name} is already linked to "${result.project.display_name}"`,
        "success",
      );
      setPickerInstallId(null);
      setPickerRepos([]);
      refresh();
    } catch (e) {
      toast(String(e), "error");
    } finally {
      clearInterval(poll);
      setLinkingRepo(null);
      setLinkStage(null);
    }
  }

  async function handleDeleteLinked(link: GitHubRepoLink, projectName: string) {
    setDeletingLink(link.id);
    try {
      // 1 repo = 1 project: removing the link removes the project it created,
      // including its files and dbt map. The GitHub repo itself is untouched.
      await deleteWorkspaceProject(link.project_id);
      toast(`Deleted project "${projectName}" and its repo link`, "success");
      setConfirmDeleteLink(null);
      refresh();
    } catch (e) {
      toast(String(e), "error");
    } finally {
      setDeletingLink(null);
    }
  }

  const linkedRepoNames = new Set(repoLinks.map((l) => l.repo_full_name));

  return (
    <div className="p-8 animate-fade-in">
      <PageHeader
        title="github"
        subtitle="settings"
        description="connect GitHub repos to workspace projects"
      />

      <TerminalBar
        path="github --status"
        status={<StatusDot status={installations.length > 0 ? "healthy" : "unknown"} size={4} pulse={false} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            accounts: <code className="text-[12px] text-[var(--color-text)]">{installations.length}</code>
          </span>
          <span className="text-[var(--color-text-dim)]">
            linked repos: <code className="text-[12px] text-[var(--color-text)]">{repoLinks.length}</code>
          </span>
        </div>
      </TerminalBar>

      {githubErrorMessage && (
        <div className="mb-6 border border-[var(--color-error)] bg-[var(--color-error)]/10 rounded-[14px] px-5 py-4 flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-4 h-4 mt-0.5 text-[var(--color-error)]" />
            <div>
              <p className="text-xs font-bold text-[var(--color-text)]">
                GitHub connection failed
              </p>
              <p className="mt-1 text-xs text-[var(--color-text-dim)]">
                {githubErrorMessage}
              </p>
            </div>
          </div>
          {githubError !== "github_app_not_configured" && (
            <button
              type="button"
              onClick={handleConnectGitHub}
              disabled={connecting}
              className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text)] bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-text-dim)] transition-colors duration-150 disabled:opacity-50"
            >
              {connecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plug className="w-3 h-3" />}
              retry
            </button>
          )}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 py-12 text-xs text-[var(--color-text-dim)]">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> loading...
        </div>
      ) : (
        <>
          {/* Connected Accounts */}
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] mb-6">
            <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
              <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
                connected accounts
              </span>
              <button
                type="button"
                onClick={handleConnectGitHub}
                disabled={connecting}
                className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text)] bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-text-dim)] transition-colors duration-150 disabled:opacity-50"
              >
                {connecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plug className="w-3 h-3" />}
                connect github
              </button>
            </div>
            {installations.length === 0 ? (
              <div className="p-8 text-center text-xs text-[var(--color-text-dim)]">
                no GitHub accounts connected — click "Connect GitHub" to get started
              </div>
            ) : (
              <div className="divide-y divide-[var(--color-border)]">
                {installations.map((inst) => (
                  <div key={inst.id} className="flex items-center justify-between px-5 py-3">
                    <div className="flex items-center gap-3">
                      <GitBranch className="w-4 h-4 text-[var(--color-text-dim)]" />
                      <div>
                        <span className="text-xs font-bold text-[var(--color-text)]">{inst.github_account_login}</span>
                        <span className="ml-2 text-[11px] text-[var(--color-text-dim)]">{inst.github_account_type}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => openRepoPicker(inst.id)}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors duration-150"
                      >
                        <LinkIcon className="w-3 h-3" /> link repo
                      </button>
                      <button
                        onClick={() => handleDisconnect(inst.id)}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-colors duration-150"
                      >
                        <Unplug className="w-3 h-3" /> disconnect
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Repo Picker */}
          {pickerInstallId && (
            <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] mb-6 animate-scale-in">
              <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
                <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
                  link a repo — a project is created for it automatically
                </span>
                <button
                  onClick={() => { setPickerInstallId(null); setPickerRepos([]); }}
                  className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors duration-150"
                >
                  cancel
                </button>
              </div>
              <div className="p-5">
                {pickerLoading ? (
                  <div className="flex items-center gap-2 py-4 text-xs text-[var(--color-text-dim)]">
                    <Loader2 className="w-3 h-3 animate-spin" /> loading repos...
                  </div>
                ) : (
                  <div className="max-h-64 overflow-y-auto divide-y divide-[var(--color-border)] border border-[var(--color-border)] rounded-[10px]">
                    {pickerRepos.map((repo) => (
                      <div key={repo.id} className="flex items-center justify-between px-3 py-2 hover:bg-[var(--color-bg-hover)]">
                        <div>
                          <span className="text-xs font-mono text-[var(--color-text)]">{repo.full_name}</span>
                          {repo.private && <span className="ml-2 text-[10px] text-[var(--color-text-dim)]">private</span>}
                          {repo.description && <p className="text-[11px] text-[var(--color-text-dim)] truncate max-w-md">{repo.description}</p>}
                        </div>
                        {linkedRepoNames.has(repo.full_name) ? (
                          <span className="px-2 py-1 text-[11px] text-[var(--color-text-dim)]">linked</span>
                        ) : (
                          <button
                            onClick={() => handleLinkRepo(repo)}
                            disabled={linkingRepo !== null}
                            className="flex items-center gap-1.5 px-2 py-1 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[6px] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors duration-150 disabled:opacity-30"
                          >
                            {linkingRepo === repo.full_name && <Loader2 className="w-3 h-3 animate-spin" />}
                            {linkingRepo === repo.full_name && linkStage ? linkStage : "link"}
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Linked Repos */}
          {repoLinks.length > 0 && (
            <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px]">
              <div className="px-5 py-3 border-b border-[var(--color-border)]">
                <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
                  linked repos
                </span>
              </div>
              <div className="divide-y divide-[var(--color-border)]">
                {repoLinks.map((link) => {
                  const project = projects.find((p) => p.id === link.project_id);
                  return (
                    <div key={link.id} className="flex items-center justify-between px-5 py-3">
                      <div className="flex items-center gap-4">
                        <div>
                          <span className="text-xs font-bold text-[var(--color-text)]">{project?.display_name || link.project_id}</span>
                        </div>
                        <span className="text-[11px] text-[var(--color-text-dim)]">&rarr;</span>
                        <div className="flex items-center gap-1.5">
                          <GitBranch className="w-3 h-3 text-[var(--color-text-dim)]" />
                          <span className="text-xs font-mono text-[var(--color-text)]">{link.repo_full_name}</span>
                          <span className="text-[11px] text-[var(--color-text-dim)]">({link.default_branch})</span>
                        </div>
                      </div>
                      {confirmDeleteLink === link.id ? (
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] text-[var(--color-error)]">
                            delete project &quot;{project?.display_name || link.project_id.slice(0, 8)}&quot; and all its files?
                          </span>
                          <button
                            onClick={() => handleDeleteLinked(link, project?.display_name || link.project_id.slice(0, 8))}
                            disabled={deletingLink !== null}
                            className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-bg)] bg-[var(--color-error)] rounded-[10px] hover:opacity-90 transition-opacity duration-150 disabled:opacity-50"
                          >
                            {deletingLink === link.id && <Loader2 className="w-3 h-3 animate-spin" />}
                            delete
                          </button>
                          <button
                            onClick={() => setConfirmDeleteLink(null)}
                            disabled={deletingLink !== null}
                            className="px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] hover:text-[var(--color-text)] transition-colors duration-150"
                          >
                            cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setConfirmDeleteLink(link.id)}
                          className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-colors duration-150"
                        >
                          <Unlink className="w-3 h-3" /> unlink
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
