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
            className="block border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4 hover:bg-[var(--color-bg-hover)] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-success)]"
          >
            <h2 className="text-base font-semibold text-[var(--color-text)]">{item.name}</h2>
            <p className="text-sm text-[var(--color-text-dim)] mt-1">
              {item.type} &middot; {new Date(item.createdAt).toLocaleString()}
            </p>
          </Link>
        </li>
      ))}
    </ul>
  );
}
