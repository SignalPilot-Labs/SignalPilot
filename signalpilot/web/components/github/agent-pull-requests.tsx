"use client";

import { ExternalLink, GitPullRequest, Loader2 } from "lucide-react";
import type { AgentPullRequest, AgentPullRequestStatus } from "~/lib/types";

interface AgentPullRequestsProps {
  pullRequests: AgentPullRequest[];
  loading: boolean;
  /** Map of project id to display name for the project column. */
  projectNames: Record<string, string>;
}

const STATUS_CLASSES: Record<AgentPullRequestStatus, string> = {
  pushed: "border-dashed border-[var(--color-text-dim)] text-[var(--color-text-dim)]",
  open: "border-[var(--color-text-dim)] text-[var(--color-text)]",
  merged: "border-[var(--color-border)] text-[var(--color-text)]",
  closed: "border-[var(--color-border)] text-[var(--color-text-dim)]",
  error: "border-[var(--color-error)] text-[var(--color-error)]",
};

const STATUS_LABELS: Partial<Record<AgentPullRequestStatus, string>> = {
  pushed: "pushed, no PR yet",
};

function StatusBadge({ status }: { status: AgentPullRequestStatus }) {
  const cls = STATUS_CLASSES[status] ?? STATUS_CLASSES.closed;
  return (
    <span
      className={`shrink-0 px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] border rounded-[6px] ${cls}`}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

function DraftBadge() {
  return (
    <span className="shrink-0 px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] border rounded-[6px] border-[var(--color-border)] text-[var(--color-text-dim)]">
      draft
    </span>
  );
}

function formatDate(epochSeconds: number): string {
  // The gateway sends Unix seconds; guard against millisecond values too.
  const ms = epochSeconds > 1e12 ? epochSeconds : epochSeconds * 1000;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function PullRequestRow({
  pr,
  projectName,
}: {
  pr: AgentPullRequest;
  projectName: string | undefined;
}) {
  const pushed = pr.status === "pushed";
  const label = pr.pr_number ? `#${pr.pr_number} ${pr.title}` : pr.title;
  const shortSha = pr.last_pushed_sha ? pr.last_pushed_sha.slice(0, 7) : null;
  return (
    <div
      className={`px-5 py-3 flex items-start justify-between gap-4 ${pushed ? "opacity-80" : ""}`}
    >
      <div className="min-w-0 flex flex-col gap-1">
        <div className="flex items-center gap-2 min-w-0">
          <GitPullRequest className="w-3.5 h-3.5 shrink-0 text-[var(--color-text-dim)]" />
          {pr.pr_url ? (
            <a
              href={pr.pr_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs font-bold text-[var(--color-text)] hover:underline truncate flex items-center gap-1"
            >
              {label}
              <ExternalLink className="w-3 h-3 shrink-0 text-[var(--color-text-dim)]" />
            </a>
          ) : (
            <span className="text-xs font-bold text-[var(--color-text)] truncate">{label}</span>
          )}
          <StatusBadge status={pr.status} />
          {pr.draft && !pushed && <DraftBadge />}
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-[var(--color-text-dim)]">
          {projectName && <span>{projectName}</span>}
          {projectName && <span>&middot;</span>}
          <span className="font-mono text-[var(--color-text)]">{pr.repo_full_name}</span>
          <span>&middot;</span>
          <span className="font-mono">{pr.github_branch}</span>
          <span>&rarr;</span>
          <span className="font-mono">{pr.base_branch}</span>
          {shortSha && (
            <>
              <span>&middot;</span>
              <span className="font-mono" title={pr.last_pushed_sha ?? undefined}>
                {shortSha}
              </span>
            </>
          )}
        </div>
        {pushed && (
          <p className="text-[11px] text-[var(--color-text-dim)]">
            branch is on GitHub; ask the chat agent to open a pull request
          </p>
        )}
        {pr.error_message && (
          <p className="text-[11px] text-[var(--color-error)] break-words">{pr.error_message}</p>
        )}
      </div>
      <span className="shrink-0 text-[11px] text-[var(--color-text-dim)]">
        {formatDate(pushed && pr.last_pushed_at ? pr.last_pushed_at : pr.created_at)}
      </span>
    </div>
  );
}

/** Pull requests the chat agent opened on behalf of this org. */
export function AgentPullRequests({ pullRequests, loading, projectNames }: AgentPullRequestsProps) {
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] mt-6">
      <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
        <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
          agent pull requests
        </span>
        <span className="text-[11px] text-[var(--color-text-dim)]">
          {pullRequests.length} total
        </span>
      </div>
      {loading ? (
        <div className="flex items-center gap-2 px-5 py-6 text-xs text-[var(--color-text-dim)]">
          <Loader2 className="w-3 h-3 animate-spin" /> loading pull requests...
        </div>
      ) : pullRequests.length === 0 ? (
        <div className="p-8 text-center text-xs text-[var(--color-text-dim)]">
          no pull requests yet. The chat agent pushes a branch and opens one when you ask it to publish changes.
        </div>
      ) : (
        <div className="divide-y divide-[var(--color-border)]">
          {pullRequests.map((pr) => (
            <PullRequestRow key={pr.id} pr={pr} projectName={projectNames[pr.project_id]} />
          ))}
        </div>
      )}
    </div>
  );
}
