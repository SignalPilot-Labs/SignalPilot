import { notFound } from "next/navigation";
import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { DbtLinkDetail } from "@/components/dbt-links/DbtLinkDetail";
import { loadDbtLink } from "@/lib/dbt-links/load-links";
import { CLOUD_DEFERRED_BODY } from "@/app/dbt-links/_consts";
import { PageHeader } from "@/components/ui/PageHeader";
import { TerminalBar } from "@/components/ui/PageHeader";

export const dynamic = "force-dynamic";

export default async function DbtLinkDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in">
        <PageHeader title="dbt link" subtitle="detail" description="dbt project link detail." />
        <TerminalBar path="dbt-links/…" />
        <EmptyState title="dbt link" body={CLOUD_DEFERRED_BODY} />
      </div>
    );
  }

  const { id } = await params;
  const def = await loadDbtLink(id);
  if (!def) notFound();

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader title="dbt link" subtitle="detail" description={def.name} />
      <TerminalBar path={`dbt-links/${id}`} />
      <DbtLinkDetail link={def} />
    </div>
  );
}
