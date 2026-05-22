"use client";

import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import {
  GitBranch,
  Loader2,
  Plug,
  Unplug,
  Link as LinkIcon,
  Unlink,
  ExternalLink,
  RefreshCw,
} from "lucide-react";
import {
  getGitHubInstallations,
  deleteGitHubInstallation,
  getGitHubRepos,
  getGitHubRepoLinks,
  linkGitHubRepo,
  unlinkGitHubRepo,
  getWorkspaceProjects,
} from "@/lib/api";
import type {
  GitHubInstallation,
  GitHubRepo,
  GitHubRepoLink,
  WorkspaceProjectInfo,
} from "@/lib/types";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";
import Link from "next/link";

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300";

export default function GitHubConnectionsPage() {
  const { toast } = useToast();
  const searchParams = useSearchParams();

  const [installations, setInstallations] = useState<GitHubInstallation[]>([]);
  const [repoLinks, setRepoLinks] = useState<GitHubRepoLink[]>([]);
  const [projects, setProjects] = useState<WorkspaceProjectInfo[]>([]);
  const [loading, setLoading] = useState(true);

  // Repo picker state
  const [pickerInstallId, setPickerInstallId] = useState<string | null>(null);
  const [pickerRepos, setPickerRepos] = useState<GitHubRepo[]>([]);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [linkingProjectId, setLinkingProjectId] = useState<string>("");

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
    }
  }, [refresh, searchParams, toast]);

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

  async function handleLinkRepo(repo: GitHubRepo) {
    if (!linkingProjectId || !pickerInstallId) return;
    try {
      await linkGitHubRepo({
        project_id: linkingProjectId,
        installation_id: pickerInstallId,
        repo_full_name: repo.full_name,
        repo_id: repo.id,
        default_branch: repo.default_branch,
      });
      toast(`Linked ${repo.full_name}`, "success");
      setPickerInstallId(null);
      setPickerRepos([]);
      setLinkingProjectId("");
      refresh();
    } catch (e) {
      toast(String(e), "error");
    }
  }

  async function handleUnlink(linkId: string) {
    try {
      await unlinkGitHubRepo(linkId);
      toast("Repo unlinked", "success");
      refresh();
    } catch (e) {
      toast(String(e), "error");
    }
  }

  const linkedProjectIds = new Set(repoLinks.map((l) => l.project_id));
  const unlinkableProjects = projects.filter((p) => !linkedProjectIds.has(p.id));

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

      {loading ? (
        <div className="flex items-center gap-2 py-12 text-xs text-[var(--color-text-dim)]">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> loading...
        </div>
      ) : (
        <>
          {/* Connected Accounts */}
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] mb-6">
            <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
              <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                connected accounts
              </span>
              <a
                href={`${GATEWAY_URL}/auth/github`}
                className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text)] bg-[var(--color-bg-input)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] transition-all tracking-wider uppercase"
              >
                <Plug className="w-3 h-3" /> connect github
              </a>
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
                        className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
                      >
                        <LinkIcon className="w-3 h-3" /> link repo
                      </button>
                      <button
                        onClick={() => handleDisconnect(inst.id)}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
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
            <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] mb-6 animate-scale-in">
              <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
                <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                  select repo & project
                </span>
                <button
                  onClick={() => { setPickerInstallId(null); setPickerRepos([]); }}
                  className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider"
                >
                  cancel
                </button>
              </div>
              <div className="p-5">
                <div className="mb-4">
                  <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">project</label>
                  <select
                    value={linkingProjectId}
                    onChange={(e) => setLinkingProjectId(e.target.value)}
                    className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none"
                  >
                    <option value="">select a project...</option>
                    {unlinkableProjects.map((p) => (
                      <option key={p.id} value={p.id}>{p.display_name}</option>
                    ))}
                  </select>
                </div>
                {pickerLoading ? (
                  <div className="flex items-center gap-2 py-4 text-xs text-[var(--color-text-dim)]">
                    <Loader2 className="w-3 h-3 animate-spin" /> loading repos...
                  </div>
                ) : (
                  <div className="max-h-64 overflow-y-auto divide-y divide-[var(--color-border)] border border-[var(--color-border)]">
                    {pickerRepos.map((repo) => (
                      <div key={repo.id} className="flex items-center justify-between px-3 py-2 hover:bg-[var(--color-bg-hover)]">
                        <div>
                          <span className="text-xs font-mono text-[var(--color-text)]">{repo.full_name}</span>
                          {repo.private && <span className="ml-2 text-[10px] text-[var(--color-text-dim)]">private</span>}
                          {repo.description && <p className="text-[11px] text-[var(--color-text-dim)] truncate max-w-md">{repo.description}</p>}
                        </div>
                        <button
                          onClick={() => handleLinkRepo(repo)}
                          disabled={!linkingProjectId}
                          className="px-2 py-1 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase disabled:opacity-30"
                        >
                          link
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Linked Repos */}
          {repoLinks.length > 0 && (
            <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
              <div className="px-5 py-3 border-b border-[var(--color-border)]">
                <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
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
                      <button
                        onClick={() => handleUnlink(link.id)}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
                      >
                        <Unlink className="w-3 h-3" /> unlink
                      </button>
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
