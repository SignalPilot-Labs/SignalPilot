"use client";

// One gallery card: a link to the dashboard with its description, owner,
// chart count, visibility, refresh schedule and last-refresh outcome.

import { LayoutGrid, RefreshCw, UserRound } from "lucide-react";
import Link from "next/link";

import type { PublishedDashboard } from "~/lib/api/dashboards";
import { refreshSummary, relativeTime } from "~/lib/dashboards/format";

import { StatusDot, VisibilityChip } from "./dashboard-chips";
import { useDashboardsClock, useDashboardsRoutes } from "./dashboards-api-context";
import { useOwnerLabel } from "./owner-label";

export function DashboardCard({ dashboard }: { dashboard: PublishedDashboard }) {
  const routes = useDashboardsRoutes();
  const now = useDashboardsClock();
  const owner = useOwnerLabel(dashboard);
  const archived = Boolean(dashboard.archived_at);
  const lastRefresh = dashboard.last_refresh_at
    ? `Refreshed ${relativeTime(dashboard.last_refresh_at, now())}`
    : "Not refreshed yet";
  return (
    <Link
      href={routes.dashboard(dashboard.slug)}
      data-testid="dashboard-card"
      data-slug={dashboard.slug}
      data-archived={archived ? "1" : "0"}
      className={`group flex min-h-[172px] flex-col rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4 transition-colors hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)] ${
        archived ? "opacity-70" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="line-clamp-2 text-[14.5px] font-semibold leading-5 text-[var(--color-text)]">
          {dashboard.name}
        </h2>
        <VisibilityChip visibility={dashboard.visibility} />
      </div>
      <p className="mt-1.5 line-clamp-2 min-h-[36px] text-[12.5px] leading-[18px] text-[var(--color-text-muted)]">
        {dashboard.description || "No description."}
      </p>
      <dl className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1.5 pt-4 text-[11.5px] text-[var(--color-text-dim)]">
        {owner && (
          <div className="flex items-center gap-1.5" title="Owner">
            <UserRound className="h-3 w-3" strokeWidth={1.5} />
            <dd data-testid="dashboard-card-owner" className="max-w-[160px] truncate">{owner}</dd>
          </div>
        )}
        <div className="flex items-center gap-1.5" title="Charts">
          <LayoutGrid className="h-3 w-3" strokeWidth={1.5} />
          <dd>
            {dashboard.chart_count} {dashboard.chart_count === 1 ? "chart" : "charts"}
          </dd>
        </div>
        <div className="flex items-center gap-1.5" title="Refresh schedule">
          <RefreshCw className="h-3 w-3" strokeWidth={1.5} />
          <dd data-testid="dashboard-card-refresh">{refreshSummary(dashboard.refresh)}</dd>
        </div>
      </dl>
      <div className="mt-2.5 flex items-center gap-1.5 text-[11.5px] text-[var(--color-text-dim)]">
        <StatusDot status={dashboard.last_refresh_status ?? "none"} />
        <span>{lastRefresh}</span>
        {archived && <span className="ml-auto uppercase tracking-[0.08em]">archived</span>}
      </div>
    </Link>
  );
}
