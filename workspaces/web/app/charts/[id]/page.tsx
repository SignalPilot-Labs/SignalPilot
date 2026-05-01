import { notFound } from "next/navigation";
import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { ChartDetail } from "@/components/charts/ChartDetail";
import { loadChartDefinition } from "@/lib/charts/load-charts";
import { CLOUD_DEFERRED_BODY } from "@/app/charts/_consts";

export const dynamic = "force-dynamic";

export default async function ChartDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <main className="p-6">
        <EmptyState title="Chart" body={CLOUD_DEFERRED_BODY} />
      </main>
    );
  }

  const { id } = await params;
  const def = await loadChartDefinition(id);
  if (!def) notFound();

  return (
    <main className="p-6">
      <ChartDetail definition={def} />
    </main>
  );
}
