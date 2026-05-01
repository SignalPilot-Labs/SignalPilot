import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { ChartBuilderForm } from "@/components/charts/builder/ChartBuilderForm";
import { CLOUD_DEFERRED_BODY } from "@/app/charts/_consts";

export const dynamic = "force-dynamic";

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
