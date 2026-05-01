import type { AgentRunV1 } from "@/lib/agent-runs/types";
import { STATUS_LABEL } from "@/components/agent-runs/_status-label";

interface AgentRunDetailProps {
  run: AgentRunV1;
}

export function AgentRunDetail({ run }: AgentRunDetailProps) {
  const heading = run.prompt.split("\n")[0].slice(0, 80);

  return (
    <article className="rounded-card border border-border bg-surface p-6 shadow-card">
      <h1 className="text-2xl font-semibold text-fg mb-4">{heading}</h1>

      <dl className="flex flex-col gap-1 text-sm">
        <div className="flex gap-2">
          <dt className="text-muted">Status</dt>
          <dd className="text-fg">{STATUS_LABEL[run.status]}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted">Created</dt>
          <dd className="text-fg">{new Date(run.createdAt).toLocaleString()}</dd>
        </div>
        <div className="flex flex-col gap-1">
          <dt className="text-muted">Prompt</dt>
          <dd className="text-fg">
            <pre className="whitespace-pre-wrap font-mono text-sm">{run.prompt}</pre>
          </dd>
        </div>

        {run.status !== "pending" && (
          <>
            {run.startedAt !== undefined && (
              <div className="flex gap-2">
                <dt className="text-muted">Started</dt>
                <dd className="text-fg">{new Date(run.startedAt).toLocaleString()}</dd>
              </div>
            )}
            {run.finishedAt !== undefined && (
              <div className="flex gap-2">
                <dt className="text-muted">Finished</dt>
                <dd className="text-fg">{new Date(run.finishedAt).toLocaleString()}</dd>
              </div>
            )}
            {run.errorMessage !== undefined && (
              <div className="flex gap-2">
                <dt className="text-muted">Error</dt>
                <dd className="text-fg">{run.errorMessage}</dd>
              </div>
            )}
            {run.summary !== undefined && (
              <div className="flex gap-2">
                <dt className="text-muted">Summary</dt>
                <dd className="text-fg">{run.summary}</dd>
              </div>
            )}
            {run.pendingApproval !== undefined && (
              <div className="flex gap-2">
                <dt className="text-muted">Pending approval</dt>
                <dd className="text-fg">{run.pendingApproval}</dd>
              </div>
            )}
          </>
        )}
      </dl>
    </article>
  );
}
