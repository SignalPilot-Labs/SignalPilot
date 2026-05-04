import { getServerEnv } from "@/lib/env";
import { EmptyState, EmptyDatabase } from "@/components/ui/EmptyState";
import { NewDbtLinkForm } from "@/components/dbt-links/NewDbtLinkForm";
import { CLOUD_DEFERRED_BODY } from "@/app/dbt-links/_consts";
import { PageHeader } from "@/components/ui/PageHeader";
import { TerminalBar } from "@/components/ui/PageHeader";

export const dynamic = "force-dynamic";

export default function DbtLinksNewPage() {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in">
        <PageHeader title="new dbt link" subtitle="upload" description="Upload a dbt project archive." />
        <TerminalBar path="dbt-links/new" />
        <EmptyState icon={<EmptyDatabase />} title="new dbt link" body={CLOUD_DEFERRED_BODY} />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader title="new dbt link" subtitle="upload" description="Upload a dbt project archive." />
      <TerminalBar path="dbt-links/new" />
      <NewDbtLinkForm />
    </div>
  );
}
