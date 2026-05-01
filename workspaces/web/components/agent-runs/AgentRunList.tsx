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
            className="block rounded-card border border-border bg-surface p-4 shadow-card hover:bg-hover transition-colors focus-visible:ring-2 focus-visible:ring-accent"
          >
            <h2 className="text-base font-semibold text-fg line-clamp-1">{item.prompt}</h2>
            <p className="text-sm text-muted mt-1">
              {STATUS_LABEL[item.status]} &middot; {new Date(item.createdAt).toLocaleString()}
            </p>
          </Link>
        </li>
      ))}
    </ul>
  );
}
