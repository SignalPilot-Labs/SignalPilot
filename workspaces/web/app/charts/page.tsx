import { getServerEnv } from "@/lib/env";
import { EmptyState, EmptyChart } from "@/components/ui/EmptyState";
import { ChartList } from "@/components/charts/ChartList";
import { loadChartDefinitions } from "@/lib/charts/load-charts";
import { CLOUD_DEFERRED_BODY } from "@/app/charts/_consts";
import { PageHeader } from "@/components/ui/PageHeader";
import { TerminalBar } from "@/components/ui/PageHeader";
import { LinkButton } from "@/components/ui/Button";

export const dynamic = "force-dynamic";

const EMPTY_LOCAL_BODY = "No charts saved yet. Create one from New chart.";

export default async function ChartsPage() {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in">
        <PageHeader
          title="charts"
          subtitle="library"
          description="Your saved chart definitions."
          actions={<LinkButton href="/charts/new" size="sm">+ new chart</LinkButton>}
        />
        <TerminalBar path="charts" />
        <EmptyState icon={<EmptyChart />} title="charts" body={CLOUD_DEFERRED_BODY} />
      </div>
    );
  }

  const definitions = await loadChartDefinitions();

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader
        title="charts"
        subtitle="library"
        description="Your saved chart definitions."
        actions={<LinkButton href="/charts/new" size="sm">+ new chart</LinkButton>}
      />
      <TerminalBar path="charts" />
      {definitions.length === 0 ? (
        <EmptyState icon={<EmptyChart />} title="charts" body={EMPTY_LOCAL_BODY} />
      ) : (
        <ChartList items={definitions} />
      )}
    </div>
  );
}
