import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { DbtLinkList } from "@/components/dbt-links/DbtLinkList";
import { loadDbtLinks } from "@/lib/dbt-links/load-links";
import { CLOUD_DEFERRED_BODY } from "@/app/dbt-links/_consts";

export const dynamic = "force-dynamic";

const EMPTY_LOCAL_BODY = "No dbt project links yet. Upload one from New link.";

export default async function DbtLinksPage() {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <main className="p-6">
        <h1 className="text-2xl font-semibold text-fg mb-4">dbt links</h1>
        <EmptyState title="dbt links" body={CLOUD_DEFERRED_BODY} />
      </main>
    );
  }

  const links = await loadDbtLinks();

  return (
    <main className="p-6">
      <h1 className="text-2xl font-semibold text-fg mb-4">dbt links</h1>
      {links.length === 0 ? (
        <EmptyState title="dbt links" body={EMPTY_LOCAL_BODY} />
      ) : (
        <DbtLinkList items={links} />
      )}
    </main>
  );
}
