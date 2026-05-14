import { getServerEnv } from "@/lib/env";
import { EmptyState, EmptyTerminal } from "@/components/ui/EmptyState";
import { AgentRunList } from "@/components/agent-runs/AgentRunList";
import { loadAgentRuns } from "@/lib/agent-runs/load-runs";
import { CLOUD_DEFERRED_BODY, EMPTY_LOCAL_BODY } from "@/app/agent-runs/_consts";
import { PageHeader } from "@/components/ui/PageHeader";
import { TerminalBar } from "@/components/ui/PageHeader";
import { LinkButton } from "@/components/ui/Button";

export const dynamic = "force-dynamic";

export default async function AgentRunsPage() {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in">
        <PageHeader
          title="agent runs"
          subtitle="history"
          description="Automated agent execution history."
          actions={<LinkButton href="/agent-runs/new" size="sm">+ new run</LinkButton>}
        />
        <TerminalBar path="agent-runs" />
        <EmptyState
          icon={<EmptyTerminal className="text-[var(--color-text-dim)]" />}
          title="agent runs"
          body={CLOUD_DEFERRED_BODY}
        />
      </div>
    );
  }

  const runs = await loadAgentRuns();

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader
        title="agent runs"
        subtitle="history"
        description="Automated agent execution history."
        actions={<LinkButton href="/agent-runs/new" size="sm">+ new run</LinkButton>}
      />
      <TerminalBar path="agent-runs" />
      {runs.length === 0 ? (
        <EmptyState
          icon={<EmptyTerminal className="text-[var(--color-text-dim)]" />}
          title="agent runs"
          body={EMPTY_LOCAL_BODY}
        />
      ) : (
        <AgentRunList items={runs} />
      )}
    </div>
  );
}
