import { loadDashboard } from "@/lib/dashboards/load-dashboards";
import { DashboardCanvas } from "@/components/dashboards/dashboard-canvas";
import { RefreshAllButton } from "@/components/dashboards/refresh-all-button";
import { EmptyState, EmptyTerminal } from "@/components/ui/empty-states";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { notFound } from "next/navigation";
import Link from "next/link";

interface PageProps {
  params: Promise<{ id: string }>;
}

export const dynamic = "force-dynamic";

export default async function DashboardDetailPage({ params }: PageProps) {
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
          <div className="flex items-center gap-2">
            {dashboard.charts.length > 0 && (
              <RefreshAllButton dashboardId={dashboard.id} />
            )}
            <Link
              href="/dashboards"
              className="px-3 py-1.5 text-[12px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all"
            >
              &larr; all dashboards
            </Link>
          </div>
        }
      />
      <TerminalBar path={`dashboards/${id}`} />

      {dashboard.charts.length === 0 ? (
        <EmptyState
          icon={EmptyTerminal}
          title="no charts yet"
          description="This dashboard has no charts. Run an agent to populate it, or add charts via the MCP tools."
        />
      ) : (
        <DashboardCanvas dashboard={dashboard} />
      )}
    </div>
  );
}
