import { listCharts, runChart } from "@/lib/api/client";
import { ChartRunResponse } from "@/lib/api/types";
import { DashboardGrid } from "@/components/dashboard/DashboardGrid";
import { ChartCard } from "@/components/charts/ChartCard";
import { ChartError } from "@/components/charts/ChartError";

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
      <main className="flex min-h-screen flex-col items-center justify-center p-8">
        <p className="text-muted">No charts in this workspace yet.</p>
      </main>
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
    <main className="p-6">
      <h1 className="text-2xl font-semibold text-fg mb-4">Workspace charts</h1>
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
    </main>
  );
}
