"use client";

/**
 * GitHub installation + repository picker shared by the eval onboarding
 * wizard and the eval config form. The caller owns the selection; this
 * component lists the connected accounts, loads the repositories of the
 * chosen account, and offers the GitHub App install flow when none exist.
 */

import { useState } from "react";
import useSWR from "swr";
import { Github, Loader2 } from "lucide-react";
import { getGitHubInstallUrl, getGitHubRepos } from "~/lib/api";
import type { GitHubInstallation, GitHubRepo } from "~/lib/types";

export type RepoSelection = {
  url: string;
  installationId: string | null;
  repoId: number | null;
};

export const EMPTY_REPO_SELECTION: RepoSelection = { url: "", installationId: null, repoId: null };

/** Class names for the wrapper, label text, and control of each field. */
export type RepoPickerStyles = { field: string; label: string; control: string };

export const ONBOARDING_PICKER_STYLES: RepoPickerStyles = { field: "ev-onboarding-field", label: "", control: "" };

export type RepoPickerProps = {
  value: RepoSelection;
  onChange: (next: RepoSelection, repo: GitHubRepo | null) => void;
  installations: GitHubInstallation[] | undefined;
  installationsLoading: boolean;
  onConnectGitHub: () => void;
  connectingGitHub: boolean;
  /** Append `.git` to the selected repository URL (the eval set convention). */
  gitSuffix?: boolean;
  /** Copy shown in the empty state under "Connect GitHub". */
  connectPrompt: string;
  styles?: RepoPickerStyles;
  testId: string;
};

/** Start the GitHub App install flow and return to `returnTo` afterwards. */
export function useGitHubConnect(returnTo: string, onError: (message: string) => void) {
  const [connecting, setConnecting] = useState(false);

  async function connectGitHub() {
    setConnecting(true);
    try {
      sessionStorage.setItem("sp_github_return_to", returnTo);
      const { install_url } = await getGitHubInstallUrl();
      window.location.assign(install_url);
    } catch (err) {
      sessionStorage.removeItem("sp_github_return_to");
      onError(err instanceof Error ? err.message : "Could not start the GitHub connection.");
      setConnecting(false);
    }
  }

  return { connectGitHub, connecting };
}

export function repoUrlFor(repo: GitHubRepo, gitSuffix: boolean): string {
  return `https://github.com/${repo.full_name}${gitSuffix ? ".git" : ""}`;
}

export function RepoPicker({
  value,
  onChange,
  installations,
  installationsLoading,
  onConnectGitHub,
  connectingGitHub,
  gitSuffix = false,
  connectPrompt,
  styles = ONBOARDING_PICKER_STYLES,
  testId,
}: RepoPickerProps) {
  const { data: repos, isLoading: reposLoading } = useSWR(
    value.installationId ? `github-repos-${value.installationId}` : null,
    () => getGitHubRepos(value.installationId as string),
  );

  if (installationsLoading) {
    return <div className="ev-private-loading"><Loader2 className="animate-spin" /> Loading GitHub accounts...</div>;
  }

  if (!installations?.length) {
    return (
      <div className="ev-connect-github" data-testid={`${testId}-connect`}>
        <Github />
        <div><strong>Connect GitHub</strong><p>{connectPrompt}</p></div>
        <button type="button" disabled={connectingGitHub} onClick={onConnectGitHub}>
          {connectingGitHub ? <Loader2 className="animate-spin" /> : <Github />}
          Connect GitHub
        </button>
      </div>
    );
  }

  return (
    <div className="ev-private-source">
      <div className="ev-private-grid">
        <label className={styles.field}>
          <span className={styles.label}>GitHub account</span>
          <select
            className={styles.control}
            data-testid={`${testId}-installation`}
            value={value.installationId ?? ""}
            onChange={(event) => onChange({ url: "", installationId: event.target.value || null, repoId: null }, null)}
          >
            <option value="">Select an account</option>
            {installations.map((installation) => (
              <option key={installation.id} value={installation.id}>{installation.github_account_login}</option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Repository</span>
          <select
            className={styles.control}
            data-testid={`${testId}-repo`}
            value={value.repoId ?? ""}
            disabled={!value.installationId || reposLoading}
            onChange={(event) => {
              const repo = repos?.find((item) => item.id === Number(event.target.value)) ?? null;
              onChange(
                { ...value, repoId: repo?.id ?? null, url: repo ? repoUrlFor(repo, gitSuffix) : "" },
                repo,
              );
            }}
          >
            <option value="">{reposLoading ? "Loading repositories..." : "Select a repository"}</option>
            {repos?.map((repo) => (
              <option key={repo.id} value={repo.id}>{repo.full_name}{repo.private ? " (private)" : ""}</option>
            ))}
          </select>
        </label>
      </div>
      <button type="button" className="ev-connect-github-secondary" disabled={connectingGitHub} onClick={onConnectGitHub}>
        <Github /> Connect another GitHub account
      </button>
    </div>
  );
}
