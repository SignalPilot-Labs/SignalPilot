import Link from "next/link";
import type { DbtLinkV1 } from "@/lib/dbt-links/types";
import { KIND_LABEL } from "@/components/dbt-links/_kind-label";
import { StatusPill } from "@/components/ui/StatusPill";
import { TimeAgo } from "@/components/ui/TimeAgo";
import { FieldRow } from "@/components/ui/FieldRow";

interface DbtLinkDetailProps {
  link: DbtLinkV1;
}

export function DbtLinkDetail({ link }: DbtLinkDetailProps) {
  return (
    <article className="bg-[var(--color-bg-card)] border border-[var(--color-border)] p-6">
      {/* Back link */}
      <Link
        href="/dbt-links"
        className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider uppercase mb-3 inline-flex items-center gap-1 transition-colors"
      >
        ← dbt links
      </Link>

      {/* Heading row */}
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-xl font-light tracking-wide text-[var(--color-text)] line-clamp-1 flex-1 min-w-0">
          {link.name}
        </h1>
        <StatusPill tone="info">{KIND_LABEL[link.kind]}</StatusPill>
      </div>

      <dl className="flex flex-col">
        <FieldRow label="Created" first>
          <span className="text-[var(--color-text-dim)]">
            <TimeAgo timestamp={link.createdAt} />
          </span>
        </FieldRow>

        <FieldRow label="Path">
          <pre className="whitespace-pre-wrap font-mono text-[13px] text-[var(--color-text)] bg-[var(--color-bg)] border border-[var(--color-border)] p-3">
            {link.relativePath}
          </pre>
        </FieldRow>
      </dl>
    </article>
  );
}
