import { notFound } from "next/navigation";
import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { DbtLinkDetail } from "@/components/dbt-links/DbtLinkDetail";
import { loadDbtLink } from "@/lib/dbt-links/load-links";
import { CLOUD_DEFERRED_BODY } from "@/app/dbt-links/_consts";

export const dynamic = "force-dynamic";

export default async function DbtLinkDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <main className="p-6">
        <EmptyState title="dbt link" body={CLOUD_DEFERRED_BODY} />
      </main>
    );
  }

  const { id } = await params;
  const def = await loadDbtLink(id);
  if (!def) notFound();

  return (
    <main className="p-6">
      <DbtLinkDetail link={def} />
    </main>
  );
}
