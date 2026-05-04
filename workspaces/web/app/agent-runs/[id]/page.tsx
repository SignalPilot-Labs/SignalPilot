import { notFound } from "next/navigation";
import { getServerEnv } from "@/lib/env";
import { EmptyState, EmptyTerminal } from "@/components/ui/EmptyState";
import { AgentRunDetail } from "@/components/agent-runs/AgentRunDetail";
import { loadAgentRun } from "@/lib/agent-runs/load-runs";
import { CLOUD_DEFERRED_BODY } from "@/app/agent-runs/_consts";
import { PageHeader } from "@/components/ui/PageHeader";
import { TerminalBar } from "@/components/ui/PageHeader";

export const dynamic = "force-dynamic";

export default async function AgentRunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in">
        <PageHeader title="agent run" subtitle="detail" description="Agent run execution detail." />
        <TerminalBar path="agent-runs/…" />
        <EmptyState icon={<EmptyTerminal />} title="agent run" body={CLOUD_DEFERRED_BODY} />
      </div>
    );
  }

  const { id } = await params;
  const run = await loadAgentRun(id);
  if (!run) notFound();

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader title="agent run" subtitle="detail" description={`Run ${id}`} />
      <TerminalBar path={`agent-runs/${id}`} />
      <AgentRunDetail run={run} />
    </div>
  );
}
