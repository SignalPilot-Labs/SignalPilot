import Link from "next/link";
import type { ChartDefinitionV1 } from "@/lib/charts/types";
import { StatusPill } from "@/components/ui/StatusPill";
import { TimeAgo } from "@/components/ui/TimeAgo";

interface ChartListProps {
  items: ChartDefinitionV1[];
}

export function ChartList({ items }: ChartListProps) {
  return (
    <ul className="flex flex-col gap-2 stagger-fade-in">
      {items.map((item) => (
        <li key={item.id}>
          <Link
            href={`/charts/${item.id}`}
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
                <StatusPill tone="info">{item.type}</StatusPill>
              </div>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
