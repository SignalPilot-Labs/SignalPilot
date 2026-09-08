"use client";

// Refresh history: the latest refreshes with their outcome, trigger, mode,
// timing, an expandable error, and a link to the chat run for agent mode.

import { ChevronDown, ChevronRight, MessageSquare, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import type { DashboardRefresh } from "~/lib/api/dashboards";
import { durationLabel, relativeTime } from "~/lib/dashboards/format";
import { dashboardRefreshModeLabel } from "~/lib/dashboards/options";

import { RefreshStatusChip } from "./dashboard-chips";
import { useDashboardsRoutes } from "./dashboards-api-context";

function RefreshRow({ refresh, now }: { refresh: DashboardRefresh; now: () => number }) {
  const routes = useDashboardsRoutes();
  const [expanded, setExpanded] = useState(false);
  const hasError = Boolean(refresh.error);
  const when = refresh.started_at ?? refresh.scheduled_for ?? refresh.created_at;
  const duration = refresh.started_at ? durationLabel(refresh.started_at, refresh.finished_at, now()) : "";
  const meta = [
    refresh.trigger === "schedule" ? "Scheduled" : "Manual",
    dashboardRefreshModeLabel(refresh.mode),
    relativeTime(when, now()),
    duration ? (refresh.finished_at ? duration : `${duration} so far`) : "",
  ].filter(Boolean);
  return (
    <li
      data-testid="dashboard-refresh-row"
      data-status={refresh.status}
      data-refresh-id={refresh.id}
      className="px-4 py-2.5"
    >
      <div className="flex items-center gap-3">
        <RefreshStatusChip status={refresh.status} />
        <p className="min-w-0 flex-1 truncate text-[11.5px] text-[var(--color-text-dim)]">
          {meta.join(" · ")}
        </p>
        {refresh.mode === "agent" && refresh.conversation_id && (
          <Link
            href={routes.chat(refresh.conversation_id)}
            data-testid="dashboard-refresh-chat-link"
            className="inline-flex items-center gap-1 text-[11.5px] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
          >
            <MessageSquare className="h-3 w-3" strokeWidth={1.5} />
            Open run
          </Link>
        )}
        {hasError && (
          <button
            type="button"
            data-testid="dashboard-refresh-toggle-error"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
            className="inline-flex items-center gap-1 text-[11.5px] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
          >
            {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {expanded ? "Hide error" : "Show error"}
          </button>
        )}
      </div>
      {hasError && expanded && (
        <pre
          data-testid="dashboard-refresh-error"
          className="mt-2 whitespace-pre-wrap break-words rounded-[10px] border border-[var(--color-error)]/30 bg-[var(--color-error)]/5 px-3 py-2 font-mono text-[11px] leading-4 text-[var(--color-error)]"
        >
          {refresh.error}
        </pre>
      )}
    </li>
  );
}

export function DashboardRefreshHistory({
  refreshes,
  now = () => Date.now(),
}: {
  refreshes: DashboardRefresh[];
  now?: () => number;
}) {
  return (
    <section
      data-testid="dashboard-refresh-history"
      aria-labelledby="dashboard-refreshes-title"
      className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)]"
    >
      <header className="flex items-center gap-2 border-b border-[var(--color-border)] px-4 py-3">
        <RefreshCw className="h-3.5 w-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
        <h2 id="dashboard-refreshes-title" className="text-[12.5px] font-medium text-[var(--color-text)]">
          Refreshes
        </h2>
        <span className="text-[11.5px] text-[var(--color-text-dim)]">{refreshes.length}</span>
      </header>
      {refreshes.length === 0 ? (
        <p className="px-4 py-6 text-center text-[12px] text-[var(--color-text-dim)]">
          No refreshes yet. Use Refresh now, or set a schedule in Settings.
        </p>
      ) : (
        <ol className="divide-y divide-[var(--color-border)]">
          {refreshes.map((refresh) => (
            <RefreshRow key={refresh.id} refresh={refresh} now={now} />
          ))}
        </ol>
      )}
    </section>
  );
}
