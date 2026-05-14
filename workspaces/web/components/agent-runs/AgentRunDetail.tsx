import Link from "next/link";
import type { AgentRunV1 } from "@/lib/agent-runs/types";
import { STATUS_LABEL } from "@/components/agent-runs/_status-label";
import { StatusPill, statusToneFor } from "@/components/ui/StatusPill";
import { TimeAgo } from "@/components/ui/TimeAgo";
import { FieldRow } from "@/components/ui/FieldRow";

interface AgentRunDetailProps {
  run: AgentRunV1;
}

export function AgentRunDetail({ run }: AgentRunDetailProps) {
  const heading = run.prompt.split("\n")[0];

  return (
    <article className="bg-[var(--color-bg-card)] border border-[var(--color-border)] p-6">
      {/* Back link */}
      <Link
        href="/agent-runs"
        className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider uppercase mb-3 inline-flex items-center gap-1 transition-colors"
      >
        ← agent runs
      </Link>

      {/* Heading row */}
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-xl font-light tracking-wide text-[var(--color-text)] line-clamp-1 flex-1 min-w-0">
          {heading}
        </h1>
        <StatusPill tone={statusToneFor(run.status)}>
          {STATUS_LABEL[run.status]}
        </StatusPill>
      </div>

      <dl className="flex flex-col">
        <FieldRow label="Created" first>
          <span className="text-[var(--color-text-dim)]">
            <TimeAgo timestamp={run.createdAt} />
          </span>
        </FieldRow>

        <FieldRow label="Prompt">
          <pre className="whitespace-pre-wrap font-mono text-[13px] text-[var(--color-text)] bg-[var(--color-bg)] border border-[var(--color-border)] p-3">
            {run.prompt}
          </pre>
        </FieldRow>

        {run.status !== "pending" && (
          <>
            {run.startedAt !== undefined && (
              <FieldRow label="Started">
                <span className="text-[var(--color-text-dim)]">
                  <TimeAgo timestamp={run.startedAt} />
                </span>
              </FieldRow>
            )}
            {run.finishedAt !== undefined && (
              <FieldRow label="Finished">
                <span className="text-[var(--color-text-dim)]">
                  <TimeAgo timestamp={run.finishedAt} />
                </span>
              </FieldRow>
            )}
            {run.errorMessage !== undefined && (
              <FieldRow label="Error">
                <span className="text-[var(--color-error)] tracking-wider">
                  {run.errorMessage}
                </span>
              </FieldRow>
            )}
            {run.summary !== undefined && (
              <FieldRow label="Summary">
                <span className="text-[var(--color-text)]">{run.summary}</span>
              </FieldRow>
            )}
            {run.pendingApproval !== undefined && (
              <FieldRow label="Pending approval">
                <span className="text-[var(--color-text)]">{run.pendingApproval}</span>
              </FieldRow>
            )}
          </>
        )}
      </dl>
    </article>
  );
}
