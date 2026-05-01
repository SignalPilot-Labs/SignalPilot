import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { AgentRunList } from "@/components/agent-runs/AgentRunList";
import { loadAgentRuns } from "@/lib/agent-runs/load-runs";
import { CLOUD_DEFERRED_BODY, EMPTY_LOCAL_BODY } from "@/app/agent-runs/_consts";

export const dynamic = "force-dynamic";

export default async function AgentRunsPage() {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <main className="p-6">
        <h1 className="text-2xl font-semibold text-fg mb-4">Agent runs</h1>
        <EmptyState title="Agent runs" body={CLOUD_DEFERRED_BODY} />
      </main>
    );
  }

  const runs = await loadAgentRuns();

  return (
    <main className="p-6">
      <h1 className="text-2xl font-semibold text-fg mb-4">Agent runs</h1>
      {runs.length === 0 ? (
        <EmptyState title="Agent runs" body={EMPTY_LOCAL_BODY} />
      ) : (
        <AgentRunList items={runs} />
      )}
    </main>
  );
}
