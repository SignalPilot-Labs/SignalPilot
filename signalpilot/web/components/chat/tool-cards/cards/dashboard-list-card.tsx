"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";
import type { CSSProperties } from "react";
import type { DashboardListEntry, DashboardListResult, RunStep } from "~/lib/chat-run-steps";
import { realDashboardsRoutes } from "~/lib/dashboards/api";
import { relativeTime } from "~/lib/dashboards/format";
import { InputPills, ProgressRail, SkeletonRows, plural } from "../card-primitives";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";

/**
 * Gallery listing card: `dashboard_list_published`. One row per published
 * dashboard the agent can see, with its chart count, visibility, when it
 * last refreshed and a link into the gallery page.
 */

const INPUT_KEYS = ["query", "limit"] as const;
const CASCADE_CAP = 24;

function listResult(step: RunStep): DashboardListResult | null {
  return step.result?.kind === "dashboard_list" ? step.result : null;
}

export function summarizeDashboardList(step: RunStep): ToolCardSummary {
  const result = listResult(step);
  const failed = step.status === "failed";
  const title = "Published dashboards";
  if (!result) return { title, stat: null, ok: !failed };
  return { title, stat: plural(result.total, "dashboard"), ok: !failed };
}

function DashboardListRunning({ step }: ToolCardContext) {
  return (
    <div data-testid="chat-dashboard-list-card">
      <div className="px-3.5 pt-3">
        <InputPills step={step} keys={INPUT_KEYS} />
      </div>
      <SkeletonRows columns={3} rows={3} />
      <ProgressRail label="Listing dashboards…" />
    </div>
  );
}

/** "refreshed 3 h ago", else the last edit when it never refreshed. */
export function dashboardFreshness(
  entry: Pick<DashboardListEntry, "lastRefreshAt" | "updatedAt">,
  now = Date.now(),
): string | null {
  if (entry.lastRefreshAt) return `refreshed ${relativeTime(entry.lastRefreshAt, now)}`;
  if (entry.updatedAt) return `updated ${relativeTime(entry.updatedAt, now)}`;
  return null;
}

function VisibilityChip({ visibility }: { visibility: string }) {
  return (
    <span
      data-testid="chat-dashboard-list-visibility"
      className="inline-flex items-center rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-1.5 py-px font-mono text-[10px] text-[var(--color-text-muted)]"
    >
      {visibility}
    </span>
  );
}

function DashboardRow({ entry, index }: { entry: DashboardListEntry; index: number }) {
  const freshness = dashboardFreshness(entry);
  return (
    <li
      data-testid="chat-dashboard-list-entry"
      data-slug={entry.slug}
      data-can-edit={entry.canEdit ? "1" : "0"}
      className="chat-tool-cascade-in px-3.5 py-2"
      style={{ "--i": Math.min(index, CASCADE_CAP) } as CSSProperties}
    >
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="min-w-0 truncate text-[12px] font-medium text-[var(--color-text)]">
          {entry.name}
        </span>
        {entry.visibility && <VisibilityChip visibility={entry.visibility} />}
        <span className="font-mono text-[10px] tabular-nums text-[var(--color-text-dim)]">
          {plural(entry.chartCount, "chart")}
        </span>
        {freshness && (
          <span className="font-mono text-[10px] text-[var(--color-text-dim)]">{freshness}</span>
        )}
        <Link
          href={realDashboardsRoutes.dashboard(entry.slug)}
          data-testid="chat-dashboard-list-open"
          className="ml-auto inline-flex flex-none items-center gap-1 text-[11px] text-[var(--color-text-muted)] underline decoration-[var(--color-border-active)] underline-offset-2 hover:text-[var(--color-text)]"
        >
          Open
          <ExternalLink className="h-3 w-3" />
        </Link>
      </div>
      {entry.description && (
        <p className="mt-0.5 truncate text-[11px] text-[var(--color-text-dim)]">{entry.description}</p>
      )}
    </li>
  );
}

function DashboardListExpanded({ step }: ToolCardContext) {
  const result = listResult(step);
  if (!result) {
    return (
      <div data-testid="chat-dashboard-list-card" className="px-3.5 py-3">
        <InputPills step={step} keys={INPUT_KEYS} />
      </div>
    );
  }
  return (
    <div data-testid="chat-dashboard-list-card">
      {result.dashboards.length === 0 ? (
        <div className="px-3.5 py-3 text-[11.5px] text-[var(--color-text-dim)]">
          No dashboards have been published yet.
        </div>
      ) : (
        <ul className="divide-y divide-[var(--color-border)]">
          {result.dashboards.map((entry, index) => (
            <DashboardRow key={entry.id || `${entry.slug}-${index}`} entry={entry} index={index} />
          ))}
        </ul>
      )}
      {(result.dashboardsTruncated || result.total > result.dashboards.length) && (
        <p
          data-testid="chat-dashboard-list-truncated"
          className="border-t border-[var(--color-border)] px-3.5 py-1.5 font-mono text-[10px] text-[var(--color-text-dim)]"
        >
          {result.total > result.dashboards.length
            ? `${result.total - result.dashboards.length} more not shown`
            : "More dashboards not shown"}
        </p>
      )}
    </div>
  );
}

registerToolCard({
  kind: "dashboard_list",
  Icon: iconForKind("dashboard_list"),
  accent: "artifact",
  summarize: summarizeDashboardList,
  Running: DashboardListRunning,
  Expanded: DashboardListExpanded,
});
