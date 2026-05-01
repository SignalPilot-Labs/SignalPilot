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
            className="block rounded-card border border-border bg-surface p-4 shadow-card hover:bg-hover transition-colors focus-visible:ring-2 focus-visible:ring-accent"
          >
            <h2 className="text-base font-semibold text-fg">{item.name}</h2>
            <p className="text-sm text-muted mt-1">
              {KIND_LABEL[item.kind]} &middot; {new Date(item.createdAt).toLocaleString()}
            </p>
          </Link>
        </li>
      ))}
    </ul>
  );
}
