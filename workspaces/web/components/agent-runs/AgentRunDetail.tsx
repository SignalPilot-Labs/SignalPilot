import type { AgentRunV1 } from "@/lib/agent-runs/types";
import { STATUS_LABEL } from "@/components/agent-runs/_status-label";

interface AgentRunDetailProps {
  run: AgentRunV1;
}

export function AgentRunDetail({ run }: AgentRunDetailProps) {
  const heading = run.prompt.split("\n")[0];

  return (
    <article className="bg-[var(--color-bg-card)] border border-[var(--color-border)] p-6">
      <h1 className="text-2xl font-semibold text-[var(--color-text)] mb-4 line-clamp-1">{heading}</h1>

      <dl className="flex flex-col gap-1 text-sm">
        <div className="flex gap-2">
          <dt className="text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px]">Status</dt>
          <dd className="text-[var(--color-text)]">{STATUS_LABEL[run.status]}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px]">Created</dt>
          <dd className="text-[var(--color-text-dim)]">{new Date(run.createdAt).toLocaleString()}</dd>
        </div>
        <div className="flex flex-col gap-1">
          <dt className="text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px]">Prompt</dt>
          <dd className="text-[var(--color-text)]">
            <pre className="whitespace-pre-wrap font-mono text-sm">{run.prompt}</pre>
          </dd>
        </div>

        {run.status !== "pending" && (
          <>
            {run.startedAt !== undefined && (
              <div className="flex gap-2">
                <dt className="text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px]">Started</dt>
                <dd className="text-[var(--color-text-dim)]">{new Date(run.startedAt).toLocaleString()}</dd>
              </div>
            )}
            {run.finishedAt !== undefined && (
              <div className="flex gap-2">
                <dt className="text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px]">Finished</dt>
                <dd className="text-[var(--color-text-dim)]">{new Date(run.finishedAt).toLocaleString()}</dd>
              </div>
            )}
            {run.errorMessage !== undefined && (
              <div className="flex gap-2">
                <dt className="text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px]">Error</dt>
                <dd className="text-[var(--color-error)]">{run.errorMessage}</dd>
              </div>
            )}
            {run.summary !== undefined && (
              <div className="flex gap-2">
                <dt className="text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px]">Summary</dt>
                <dd className="text-[var(--color-text)]">{run.summary}</dd>
              </div>
            )}
            {run.pendingApproval !== undefined && (
              <div className="flex gap-2">
                <dt className="text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px]">Pending approval</dt>
                <dd className="text-[var(--color-text)]">{run.pendingApproval}</dd>
              </div>
            )}
          </>
        )}
      </dl>
    </article>
  );
}
