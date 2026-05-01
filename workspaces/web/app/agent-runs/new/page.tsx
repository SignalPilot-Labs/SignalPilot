import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { NewAgentRunForm } from "@/components/agent-runs/NewAgentRunForm";
import { CLOUD_DEFERRED_BODY } from "@/app/agent-runs/_consts";
import { PageHeader } from "@/components/ui/PageHeader";
import { TerminalBar } from "@/components/ui/PageHeader";

export const dynamic = "force-dynamic";

export default function AgentRunsNewPage() {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in">
        <PageHeader title="new agent run" subtitle="prompt" description="Submit a prompt to start a new agent run." />
        <TerminalBar path="agent-runs/new" />
        <EmptyState title="new agent run" body={CLOUD_DEFERRED_BODY} />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader title="new agent run" subtitle="prompt" description="Submit a prompt to start a new agent run." />
      <TerminalBar path="agent-runs/new" />
      <NewAgentRunForm />
    </div>
  );
}
