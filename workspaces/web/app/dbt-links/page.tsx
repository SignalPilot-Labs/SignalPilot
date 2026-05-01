import { getServerEnv } from "@/lib/env";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { DbtLinkList } from "@/components/dbt-links/DbtLinkList";
import { loadDbtLinks } from "@/lib/dbt-links/load-links";
import { CLOUD_DEFERRED_BODY } from "@/app/dbt-links/_consts";
import { PageHeader } from "@/components/ui/PageHeader";
import { TerminalBar } from "@/components/ui/PageHeader";
import { LinkButton } from "@/components/ui/Button";

export const dynamic = "force-dynamic";

const EMPTY_LOCAL_BODY = "No dbt project links yet. Upload one from New link.";

export default async function DbtLinksPage() {
  const env = getServerEnv();

  if (env.mode === "cloud") {
    return (
      <div className="p-8 max-w-[1400px] animate-fade-in">
        <PageHeader
          title="dbt links"
          subtitle="projects"
          description="Linked dbt project archives."
          actions={<LinkButton href="/dbt-links/new" size="sm">+ new link</LinkButton>}
        />
        <TerminalBar path="dbt-links" />
        <EmptyState title="dbt links" body={CLOUD_DEFERRED_BODY} />
      </div>
    );
  }

  const links = await loadDbtLinks();

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader
        title="dbt links"
        subtitle="projects"
        description="Linked dbt project archives."
        actions={<LinkButton href="/dbt-links/new" size="sm">+ new link</LinkButton>}
      />
      <TerminalBar path="dbt-links" />
      {links.length === 0 ? (
        <EmptyState title="dbt links" body={EMPTY_LOCAL_BODY} />
      ) : (
        <DbtLinkList items={links} />
      )}
    </div>
  );
}
