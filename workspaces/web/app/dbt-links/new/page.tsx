import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { NewDbtLinkForm } from "@/components/dbt-links/NewDbtLinkForm";
import { CLOUD_DEFERRED_BODY } from "@/app/dbt-links/_consts";

export const dynamic = "force-dynamic";

export default function DbtLinksNewPage() {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <main className="p-6">
        <EmptyState title="New dbt link" body={CLOUD_DEFERRED_BODY} />
      </main>
    );
  }

  return (
    <main className="p-6">
      <NewDbtLinkForm />
    </main>
  );
}
