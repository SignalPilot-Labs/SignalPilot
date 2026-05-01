import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { NewAgentRunForm } from "@/components/agent-runs/NewAgentRunForm";
import { CLOUD_DEFERRED_BODY } from "@/app/agent-runs/_consts";

export const dynamic = "force-dynamic";

export default function AgentRunsNewPage() {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <main className="p-6">
        <EmptyState title="New agent run" body={CLOUD_DEFERRED_BODY} />
      </main>
    );
  }

  return (
    <main className="p-6">
      <NewAgentRunForm />
    </main>
  );
}
