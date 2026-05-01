import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { ChartBuilderForm } from "@/components/charts/builder/ChartBuilderForm";
import { CLOUD_DEFERRED_BODY } from "@/app/charts/_consts";
import { PageHeader } from "@/components/ui/PageHeader";
import { TerminalBar } from "@/components/ui/PageHeader";

export const dynamic = "force-dynamic";

export default function ChartsNewPage() {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in">
        <PageHeader title="new chart" subtitle="builder" description="Define a new chart with SQL." />
        <TerminalBar path="charts/new" />
        <EmptyState title="new chart" body={CLOUD_DEFERRED_BODY} />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader title="new chart" subtitle="builder" description="Define a new chart with SQL." />
      <TerminalBar path="charts/new" />
      <ChartBuilderForm />
    </div>
  );
}
