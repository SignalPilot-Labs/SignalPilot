import Link from "next/link";
import type { ChartDefinitionV1 } from "@/lib/charts/types";

interface ChartListProps {
  items: ChartDefinitionV1[];
}

export function ChartList({ items }: ChartListProps) {
  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => (
        <li key={item.id}>
          <Link
            href={`/charts/${item.id}`}
            className="block rounded-card border border-border bg-surface p-4 shadow-card hover:bg-hover transition-colors"
          >
            <h2 className="text-base font-semibold text-fg">{item.name}</h2>
            <p className="text-sm text-muted mt-1">
              {item.type} &middot; {new Date(item.createdAt).toLocaleString()}
            </p>
          </Link>
        </li>
      ))}
    </ul>
  );
}
