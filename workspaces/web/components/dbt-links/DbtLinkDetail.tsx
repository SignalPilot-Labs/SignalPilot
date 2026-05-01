import type { DbtLinkV1 } from "@/lib/dbt-links/types";
import { KIND_LABEL } from "@/components/dbt-links/_kind-label";

interface DbtLinkDetailProps {
  link: DbtLinkV1;
}

export function DbtLinkDetail({ link }: DbtLinkDetailProps) {
  return (
    <article className="bg-[var(--color-bg-card)] border border-[var(--color-border)] p-6">
      <h1 className="text-2xl font-semibold text-[var(--color-text)] mb-4">{link.name}</h1>

      <dl className="flex flex-col gap-1 text-sm">
        <div className="flex gap-2">
          <dt className="text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px]">Kind</dt>
          <dd className="text-[var(--color-text)]">{KIND_LABEL[link.kind]}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px]">Created</dt>
          <dd className="text-[var(--color-text-dim)]">{new Date(link.createdAt).toLocaleString()}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px]">Path</dt>
          <dd className="text-[var(--color-text)]">
            <code className="font-mono">{link.relativePath}</code>
          </dd>
        </div>
      </dl>
    </article>
  );
}
