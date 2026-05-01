import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { ChartList } from "@/components/charts/ChartList";
import { loadChartDefinitions } from "@/lib/charts/load-charts";
import { CLOUD_DEFERRED_BODY } from "@/app/charts/_consts";

export const dynamic = "force-dynamic";

const EMPTY_LOCAL_BODY = "No charts saved yet. Create one from New chart.";

export default async function ChartsPage() {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <main className="p-6">
        <h1 className="text-2xl font-semibold text-fg mb-4">Charts</h1>
        <EmptyState title="Charts" body={CLOUD_DEFERRED_BODY} />
      </main>
    );
  }

  const definitions = await loadChartDefinitions();

  return (
    <main className="p-6">
      <h1 className="text-2xl font-semibold text-fg mb-4">Charts</h1>
      {definitions.length === 0 ? (
        <EmptyState title="Charts" body={EMPTY_LOCAL_BODY} />
      ) : (
        <ChartList items={definitions} />
      )}
    </main>
  );
}
