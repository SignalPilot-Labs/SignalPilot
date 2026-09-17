"use client";

import { GitBranch, Loader2, RefreshCw, Unplug, Link as LinkIcon } from "lucide-react";
import type { GitHubInstallation } from "~/lib/types";

interface InstallationCardProps {
  installation: GitHubInstallation;
  refreshing: boolean;
  onLinkRepo: (installationId: string) => void;
  onRefresh: (installationId: string) => void;
  onDisconnect: (installationId: string) => void;
}

const ACTION_BUTTON =
  "flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors duration-150 disabled:opacity-50";

function repoCountLabel(count: number): string {
  if (count === 1) return "1 repository";
  return `${count} repositories`;
}

/** One connected GitHub App installation row with its per-row actions. */
export function InstallationCard({
  installation: inst,
  refreshing,
  onLinkRepo,
  onRefresh,
  onDisconnect,
}: InstallationCardProps) {
  const count = inst.authorized_repository_count ?? 0;
  return (
    <div className="flex items-center justify-between px-5 py-3">
      <div className="flex items-center gap-3">
        <GitBranch className="w-4 h-4 text-[var(--color-text-dim)]" />
        <div>
          <span className="text-xs font-bold text-[var(--color-text)]">
            {inst.github_account_login}
          </span>
          <span className="ml-2 text-[11px] text-[var(--color-text-dim)]">
            {inst.github_account_type}
          </span>
          <span className="ml-2 text-[11px] text-[var(--color-text-dim)]">
            &middot; {repoCountLabel(count)}
          </span>
          {inst.status && inst.status !== "active" && (
            <span className="ml-2 text-[10px] uppercase tracking-[0.08em] text-[var(--color-text-dim)]">
              {inst.status}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onRefresh(inst.id)}
          disabled={refreshing}
          title="Re-list repositories from GitHub"
          className={ACTION_BUTTON}
        >
          {refreshing ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <RefreshCw className="w-3 h-3" />
          )}
          refresh repositories
        </button>
        <button type="button" onClick={() => onLinkRepo(inst.id)} className={ACTION_BUTTON}>
          <LinkIcon className="w-3 h-3" /> link repo
        </button>
        <button
          type="button"
          onClick={() => onDisconnect(inst.id)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-colors duration-150"
        >
          <Unplug className="w-3 h-3" /> disconnect
        </button>
      </div>
    </div>
  );
}
