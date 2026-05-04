import Link from "next/link";
import type { DbtLinkV1 } from "@/lib/dbt-links/types";
import { KIND_LABEL } from "@/components/dbt-links/_kind-label";
import { StatusPill } from "@/components/ui/StatusPill";
import { TimeAgo } from "@/components/ui/TimeAgo";

interface DbtLinkListProps {
  items: DbtLinkV1[];
}

export function DbtLinkList({ items }: DbtLinkListProps) {
  return (
    <ul className="flex flex-col gap-2 stagger-fade-in">
      {items.map((item) => (
        <li key={item.id}>
          <Link
            href={`/dbt-links/${item.id}`}
            className="card-radial-glow block border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4 hover:bg-[var(--color-bg-hover)] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-success)]"
          >
            <div className="flex items-start gap-4">
              <div className="flex-1 min-w-0">
                <h2 className="text-base font-semibold text-[var(--color-text)] line-clamp-1">
                  {item.name}
                </h2>
                <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider mt-1">
                  <TimeAgo timestamp={item.createdAt} />
                  {" · "}
                  {item.id.slice(0, 8)}
                </p>
              </div>
              <div className="flex-shrink-0 mt-0.5">
                <StatusPill tone="info">{KIND_LABEL[item.kind]}</StatusPill>
              </div>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
