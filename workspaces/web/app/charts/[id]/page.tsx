import { notFound } from "next/navigation";
import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { ChartDetail } from "@/components/charts/ChartDetail";
import { loadChartDefinition } from "@/lib/charts/load-charts";
import { CLOUD_DEFERRED_BODY } from "@/app/charts/_consts";
import { PageHeader } from "@/components/ui/PageHeader";
import { TerminalBar } from "@/components/ui/PageHeader";

export const dynamic = "force-dynamic";

export default async function ChartDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in">
        <PageHeader title="chart" subtitle="detail" description="Chart definition and preview." />
        <TerminalBar path="charts" />
        <EmptyState title="chart" body={CLOUD_DEFERRED_BODY} />
      </div>
    );
  }

  const { id } = await params;
  const def = await loadChartDefinition(id);
  if (!def) notFound();

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader title="chart" subtitle="detail" description={def.name} />
      <TerminalBar path={`charts/${id}`} />
      <ChartDetail definition={def} />
    </div>
  );
}
