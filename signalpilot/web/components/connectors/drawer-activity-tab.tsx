"use client";

import { Activity } from "lucide-react";
import { useEffect, useState } from "react";
import type { ConnectorDetail, ToolCall } from "~/lib/api/mcp-connectors";
import { Skeleton } from "~/components/ui/skeleton";
import { useConnectors } from "./connectors-context";
import { Chip, Notice, timeAgo } from "./ui";

const OUTCOME: Record<ToolCall["outcome"], { label: string; tone: "read" | "destructive" | "write" }> = {
  ok: { label: "ok", tone: "read" },
  error: { label: "error", tone: "destructive" },
  denied: { label: "denied", tone: "write" },
};

/**
 * Who made the call: the gateway's resolved label (email or display name),
 * "you" for the caller, and only as a last resort a truncated id with the
 * full id in a tooltip. Never a 27-character hash as a name.
 */
export function describeCaller(
  call: Pick<ToolCall, "user_id" | "user_label">,
  currentUserId: string | null,
): { label: string; title?: string; you: boolean } {
  const you = Boolean(currentUserId && call.user_id === currentUserId);
  if (call.user_label) return { label: you ? `${call.user_label} (you)` : call.user_label, you };
  if (you) return { label: "you", you };
  const stem = call.user_id.replace(/^user_/, "");
  return { label: stem.length > 8 ? `${stem.slice(0, 6)}…` : stem, title: call.user_id, you };
}

/** Last 50 calls the proxy recorded: tool · who · when · outcome · duration. */
export function DrawerActivityTab({ connector }: { connector: ConnectorDetail }) {
  const { api, currentUserId } = useConnectors();
  const [calls, setCalls] = useState<ToolCall[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setCalls(null);
    api
      .activity(connector.id)
      .then((next) => active && setCalls(next))
      .catch((caught: Error) => active && setError(caught.message));
    return () => {
      active = false;
    };
  }, [api, connector.id]);

  if (connector.transport === "stdio") {
    return (
      <Notice tone="info" testId="drawer-activity-sandbox">
        Calls to a sandbox connector happen inside the agent&apos;s sandbox, so SignalPilot doesn&apos;t record
        them. The chat transcript shows each call as it happens.
      </Notice>
    );
  }
  if (error) {
    return (
      <p role="alert" className="text-[12.5px] text-[var(--color-error)]">
        We couldn&apos;t load activity: {error}
      </p>
    );
  }
  if (!calls) {
    return (
      <div className="space-y-2" aria-busy="true">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full rounded-[var(--radius-ctl)]" />
        ))}
      </div>
    );
  }
  if (calls.length === 0) {
    return (
      <div className="flex flex-col items-center py-14 text-center" data-testid="drawer-activity-empty">
        <Activity className="h-6 w-6 text-[var(--color-text-dim)]" aria-hidden="true" />
        <p className="mt-3 text-[13px] text-[var(--color-text-muted)]">No calls yet</p>
        <p className="mt-1 max-w-xs text-[12px] text-[var(--color-text-dim)]">
          Every call the agent makes through this connector shows up here, with who made it.
        </p>
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)]">
      <table className="w-full text-left text-[12px]" data-testid="drawer-activity-table">
        <thead className="text-[10.5px] uppercase tracking-[0.08em] text-[var(--color-text-dim)]">
          <tr className="border-b border-[var(--color-border)]">
            <th className="px-3.5 py-2 font-medium">Tool</th>
            <th className="px-3 py-2 font-medium">Who</th>
            <th className="px-3 py-2 font-medium">When</th>
            <th className="px-3 py-2 font-medium">Outcome</th>
            <th className="px-3.5 py-2 text-right font-medium">Took</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--color-border)]">
          {calls.map((call) => {
            const outcome = OUTCOME[call.outcome];
            const caller = describeCaller(call, currentUserId);
            return (
              <tr key={call.id} className="align-top">
                <td className="px-3.5 py-2.5">
                  <span className="font-mono text-[11.5px] text-[var(--color-text)]">{call.tool}</span>
                  {call.error && (
                    <p className="mt-0.5 max-w-[240px] truncate text-[11px] text-[var(--color-text-dim)]" title={call.error}>
                      {call.error}
                    </p>
                  )}
                </td>
                <td
                  className={`max-w-[180px] truncate px-3 py-2.5 ${caller.you ? "text-[var(--color-text)]" : "text-[var(--color-text-muted)]"}`}
                  title={caller.title}
                  data-testid="activity-who"
                >
                  {caller.label}
                </td>
                <td className="whitespace-nowrap px-3 py-2.5 text-[var(--color-text-muted)]">{timeAgo(call.called_at)}</td>
                <td className="px-3 py-2.5">
                  <Chip tone={outcome.tone}>{outcome.label}</Chip>
                </td>
                <td className="whitespace-nowrap px-3.5 py-2.5 text-right font-mono tabular-nums text-[var(--color-text-dim)]">
                  {call.duration_ms >= 1000 ? `${(call.duration_ms / 1000).toFixed(1)}s` : `${call.duration_ms}ms`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
