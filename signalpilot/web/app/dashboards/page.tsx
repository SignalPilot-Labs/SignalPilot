import { loadDashboards } from "@/lib/dashboards/load-dashboards";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { DashboardListClient } from "@/components/dashboards/dashboard-list-client";

export const dynamic = "force-dynamic";

export default async function DashboardsPage() {
  const dashboards = await loadDashboards();

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader
        title="dashboards"
        subtitle="analytics"
        description="Create and view your data dashboards."
      />
      <TerminalBar path="dashboards --list" />
      <DashboardListClient dashboards={dashboards} />
    </div>
  );
}
