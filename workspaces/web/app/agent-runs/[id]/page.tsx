import { notFound } from "next/navigation";
import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { AgentRunDetail } from "@/components/agent-runs/AgentRunDetail";
import { loadAgentRun } from "@/lib/agent-runs/load-runs";
import { CLOUD_DEFERRED_BODY } from "@/app/agent-runs/_consts";

export const dynamic = "force-dynamic";

export default async function AgentRunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <main className="p-6">
        <EmptyState title="Agent run" body={CLOUD_DEFERRED_BODY} />
      </main>
    );
  }

  const { id } = await params;
  const run = await loadAgentRun(id);
  if (!run) notFound();

  return (
    <main className="p-6">
      <AgentRunDetail run={run} />
    </main>
  );
}
