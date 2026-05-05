import { loadDashboards } from "@/lib/dashboards/load-dashboards";
import { PageHeader, TerminalBar } from "@/components/ui/PageHeader";
import { DashboardListClient } from "@/components/dashboard/DashboardListClient";

export const dynamic = "force-dynamic";

export default async function DashboardsPage() {
  const dashboards = await loadDashboards();

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader
        title="dashboards"
        subtitle="overview"
        description="Create and view your dashboards."
      />
      <TerminalBar path="dashboards" />
      <DashboardListClient dashboards={dashboards} />
    </div>
  );
}
