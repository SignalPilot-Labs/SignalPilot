import { listCharts, runChart } from "@/lib/api/client";
import { ChartRunResponse } from "@/lib/api/types";
import { DashboardGrid } from "@/components/dashboard/DashboardGrid";
import { ChartCard } from "@/components/charts/ChartCard";
import { ChartError } from "@/components/charts/ChartError";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { TerminalBar } from "@/components/ui/PageHeader";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function DashboardPage({ params }: PageProps) {
  const { id } = await params;
  const workspaceId = id;

  const chartList = await listCharts(workspaceId);
  const { items } = chartList;

  if (items.length === 0) {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in">
        <PageHeader title="dashboard" subtitle="canvas" description={`Workspace ${id}`} />
        <TerminalBar path={`dashboards/${id}`} />
        <EmptyState
          title="no charts yet"
          body="This workspace has no charts. Create one to populate the dashboard."
        />
      </div>
    );
  }

  const runResults = await Promise.all(
    items.map(async (chart) => {
      try {
        const result = await runChart(chart.id);
        return { ok: true as const, result };
      } catch (err) {
        const error = err instanceof Error ? err.message : "Failed to run chart";
        const code =
          err != null &&
          typeof err === "object" &&
          "code" in err &&
          typeof (err as { code: unknown }).code === "string"
            ? (err as { code: string }).code
            : undefined;
        return { ok: false as const, error, code };
      }
    })
  );

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader title="dashboard" subtitle="canvas" description={`Workspace ${id}`} />
      <TerminalBar path={`dashboards/${id}`} />
      <DashboardGrid>
        {items.map((chart, i) => {
          const run = runResults[i];
          if (!run) return null;
          if (!run.ok) {
            return (
              <ChartError
                key={chart.id}
                code={run.code}
                message={run.error}
              />
            );
          }
          const runResult: ChartRunResponse = run.result;
          return (
            <ChartCard key={chart.id} chart={chart} runResult={runResult} />
          );
        })}
      </DashboardGrid>
    </div>
  );
}
