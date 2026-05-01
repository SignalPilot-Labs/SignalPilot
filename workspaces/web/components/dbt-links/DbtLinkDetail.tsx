import type { DbtLinkV1 } from "@/lib/dbt-links/types";
import { KIND_LABEL } from "@/components/dbt-links/_kind-label";

interface DbtLinkDetailProps {
  link: DbtLinkV1;
}

export function DbtLinkDetail({ link }: DbtLinkDetailProps) {
  return (
    <article className="rounded-card border border-border bg-surface p-6 shadow-card">
      <h1 className="text-2xl font-semibold text-fg mb-4">{link.name}</h1>

      <dl className="flex flex-col gap-1 text-sm">
        <div className="flex gap-2">
          <dt className="text-muted">Kind</dt>
          <dd className="text-fg">{KIND_LABEL[link.kind]}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted">Created</dt>
          <dd className="text-fg">{link.createdAt}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted">Path</dt>
          <dd className="text-fg">
            <code className="font-mono">{link.relativePath}</code>
          </dd>
        </div>
      </dl>
    </article>
  );
}
