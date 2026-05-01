import Link from "next/link";
import type { AgentRunV1 } from "@/lib/agent-runs/types";
import { STATUS_LABEL } from "@/components/agent-runs/_status-label";

interface AgentRunListProps {
  items: AgentRunV1[];
}

export function AgentRunList({ items }: AgentRunListProps) {
  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => (
        <li key={item.id}>
          <Link
            href={`/agent-runs/${item.id}`}
            className="block border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4 hover:bg-[var(--color-bg-hover)] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-success)]"
          >
            <h2 className="text-base font-semibold text-[var(--color-text)] line-clamp-1">{item.prompt}</h2>
            <p className="text-sm text-[var(--color-text-dim)] mt-1">
              {STATUS_LABEL[item.status]} &middot; {new Date(item.createdAt).toLocaleString()}
            </p>
          </Link>
        </li>
      ))}
    </ul>
  );
}
