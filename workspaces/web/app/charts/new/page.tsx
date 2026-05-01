import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { ChartBuilderForm } from "@/components/charts/builder/ChartBuilderForm";

export const dynamic = "force-dynamic";

export const CLOUD_DEFERRED_BODY = "Chart builder coming soon.";

export default function ChartsNewPage() {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <main className="p-6">
        <EmptyState title="Chart builder" body={CLOUD_DEFERRED_BODY} />
      </main>
    );
  }

  return (
    <main className="p-6">
      <ChartBuilderForm />
    </main>
  );
}
