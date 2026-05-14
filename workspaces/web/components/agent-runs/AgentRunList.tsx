import Link from "next/link";
import type { AgentRunV1 } from "@/lib/agent-runs/types";
import { STATUS_LABEL } from "@/components/agent-runs/_status-label";
import { StatusPill, statusToneFor } from "@/components/ui/StatusPill";
import { TimeAgo } from "@/components/ui/TimeAgo";

interface AgentRunListProps {
  items: AgentRunV1[];
}

export function AgentRunList({ items }: AgentRunListProps) {
  return (
    <ul className="flex flex-col gap-2 stagger-fade-in">
      {items.map((item) => (
        <li key={item.id}>
          <Link
            href={`/agent-runs/${item.id}`}
            className="card-radial-glow block border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4 hover:bg-[var(--color-bg-hover)] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-success)]"
          >
            <div className="flex items-start gap-4">
              <div className="flex-1 min-w-0">
                <h2 className="text-base font-semibold text-[var(--color-text)] line-clamp-1">
                  {item.prompt}
                </h2>
                <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider mt-1">
                  <TimeAgo timestamp={item.createdAt} />
                  {" · "}
                  Run · {item.id.slice(0, 8)}
                </p>
              </div>
              <div className="flex-shrink-0 mt-0.5">
                <StatusPill tone={statusToneFor(item.status)}>
                  {STATUS_LABEL[item.status]}
                </StatusPill>
              </div>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
