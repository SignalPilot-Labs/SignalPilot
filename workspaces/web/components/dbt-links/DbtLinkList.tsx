import Link from "next/link";
import type { DbtLinkV1 } from "@/lib/dbt-links/types";
import { KIND_LABEL } from "@/components/dbt-links/_kind-label";

interface DbtLinkListProps {
  items: DbtLinkV1[];
}

export function DbtLinkList({ items }: DbtLinkListProps) {
  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => (
        <li key={item.id}>
          <Link
            href={`/dbt-links/${item.id}`}
            className="block border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4 hover:bg-[var(--color-bg-hover)] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-success)]"
          >
            <h2 className="text-base font-semibold text-[var(--color-text)]">{item.name}</h2>
            <p className="text-sm text-[var(--color-text-dim)] mt-1">
              {KIND_LABEL[item.kind]} &middot; {new Date(item.createdAt).toLocaleString()}
            </p>
          </Link>
        </li>
      ))}
    </ul>
  );
}
