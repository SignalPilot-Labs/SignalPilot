import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { WorkspaceList } from "@/components/dashboard/WorkspaceList";

export const dynamic = "force-dynamic";

export const CLOUD_DEFERRED_BODY = "Workspace listing is not available yet.";
export const EMPTY_LOCAL_BODY =
  "Set WORKSPACES_LOCAL_IDS in your environment to populate this list.";

export default function DashboardsPage() {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <main className="p-6">
        <h1 className="text-2xl font-semibold text-fg mb-4">Dashboards</h1>
        <EmptyState title="Workspaces" body={CLOUD_DEFERRED_BODY} />
      </main>
    );
  }

  return (
    <main className="p-6">
      <h1 className="text-2xl font-semibold text-fg mb-4">Dashboards</h1>
      {env.localWorkspaceIds.length === 0 ? (
        <EmptyState title="Workspaces" body={EMPTY_LOCAL_BODY} />
      ) : (
        <WorkspaceList items={env.localWorkspaceIds} />
      )}
    </main>
  );
}
