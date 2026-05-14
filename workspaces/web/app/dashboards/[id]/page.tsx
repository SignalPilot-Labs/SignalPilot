import { loadDashboard } from "@/lib/dashboards/load-dashboards";
import { DashboardCanvas } from "@/components/dashboard/DashboardCanvas";
import { EmptyState, EmptyChart } from "@/components/ui/EmptyState";
import { PageHeader, TerminalBar } from "@/components/ui/PageHeader";
import { LinkButton } from "@/components/ui/Button";
import { notFound } from "next/navigation";

interface PageProps {
  params: Promise<{ id: string }>;
}

export const dynamic = "force-dynamic";

export default async function DashboardPage({ params }: PageProps) {
  const { id } = await params;
  const dashboard = await loadDashboard(id);

  if (!dashboard) {
    notFound();
  }

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader
        title={dashboard.name}
        subtitle="dashboard"
        description={dashboard.description || `${dashboard.charts.length} chart${dashboard.charts.length !== 1 ? "s" : ""}`}
        actions={
          <LinkButton href="/dashboards" variant="secondary" size="sm">
            &larr; all dashboards
          </LinkButton>
        }
      />
      <TerminalBar path={`dashboards/${id}`} />

      {dashboard.charts.length === 0 ? (
        <EmptyState
          icon={<EmptyChart />}
          title="no charts yet"
          body="This dashboard has no charts. Run an agent to populate it, or add charts via the MCP tools."
        />
      ) : (
        <DashboardCanvas dashboard={dashboard} />
      )}
    </div>
  );
}
