import { getServerEnv } from "@/lib/env";
import { EmptyState, EmptyList } from "@/components/ui/EmptyState";
import { WorkspaceList } from "@/components/dashboard/WorkspaceList";
import { PageHeader } from "@/components/ui/PageHeader";
import { TerminalBar } from "@/components/ui/PageHeader";
import { LinkButton } from "@/components/ui/Button";

export const dynamic = "force-dynamic";

export const CLOUD_DEFERRED_BODY = "Workspace listing is not available yet.";
export const EMPTY_LOCAL_BODY =
  "Set WORKSPACES_LOCAL_IDS in your environment to populate this list.";

export default function DashboardsPage() {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in">
        <PageHeader
          title="dashboards"
          subtitle="workspaces"
          description="Select a workspace to view its charts."
        />
        <TerminalBar path="dashboards" />
        <EmptyState icon={<EmptyList />} title="workspaces" body={CLOUD_DEFERRED_BODY} />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader
        title="dashboards"
        subtitle="workspaces"
        description="Select a workspace to view its charts."
      />
      <TerminalBar path="dashboards" />
      {env.localWorkspaceIds.length === 0 ? (
        <EmptyState icon={<EmptyList />} title="workspaces" body={EMPTY_LOCAL_BODY} />
      ) : (
        <WorkspaceList items={env.localWorkspaceIds} />
      )}
    </div>
  );
}
