"use client";

// Header of a published dashboard: identity, version and refresh lines,
// and the action row (Refresh now, Settings, Edit in chat, Download JSON,
// overflow with Archive/Unarchive and Delete).

import {
  ArrowDownToLine,
  ArrowLeft,
  MessageSquarePlus,
  MoreHorizontal,
  RefreshCw,
  Settings2,
} from "lucide-react";
import Link from "next/link";

import type { PublishedDashboard } from "~/lib/api/dashboards";
import { refreshStatusLine, refreshSummary, relativeTime } from "~/lib/dashboards/format";
import { Menu, useMenuTrigger } from "~/components/ui/menu";

import { BUTTON_CLASS, PRIMARY_BUTTON_CLASS, StatusDot, VisibilityChip } from "./dashboard-chips";
import { useDashboardsClock, useDashboardsRoutes } from "./dashboards-api-context";
import { useOwnerLabel } from "./owner-label";

export type DashboardHeaderActions = {
  onRefreshNow: () => void;
  onOpenSettings: () => void;
  onEditInChat: () => void;
  onDownloadJson: () => void;
  onArchiveToggle: () => void;
  onDelete: () => void;
};

export function DashboardHeader({
  dashboard,
  publishedAt,
  refreshing,
  pollError = null,
  busy,
  actions,
}: {
  dashboard: PublishedDashboard;
  /** `created_at` of the live version; the dashboard row's `updated_at` moves on every settings save. */
  publishedAt: string | null;
  /** A refresh is queued or running (ours or someone else's). */
  refreshing: boolean;
  /** Progress polling gave up; shown in place of the refresh line. */
  pollError?: string | null;
  /** A mutation is in flight; the action row waits for it. */
  busy: boolean;
  actions: DashboardHeaderActions;
}) {
  const routes = useDashboardsRoutes();
  const now = useDashboardsClock();
  const menu = useMenuTrigger();
  const archived = Boolean(dashboard.archived_at);
  const canEdit = dashboard.can_edit;
  const owner = useOwnerLabel(dashboard);
  const versionLine = dashboard.current_version_no
    ? `Version ${dashboard.current_version_no}, published ${relativeTime(publishedAt ?? dashboard.updated_at, now())}`
    : "No version yet";

  return (
    <header data-testid="dashboard-header" className="mb-5">
      <Link
        href={routes.gallery}
        className="inline-flex items-center gap-1.5 text-[12px] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Dashboards
      </Link>
      <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1
              data-testid="dashboard-title"
              className="text-[22px] font-semibold leading-7 tracking-[-0.01em] text-[var(--color-text)]"
            >
              {dashboard.name}
            </h1>
            <VisibilityChip visibility={dashboard.visibility} />
            {archived && (
              <span className="rounded-full border border-[var(--color-warning)]/40 px-2 py-0.5 text-[10.5px] uppercase tracking-[0.08em] text-[var(--color-warning)]">
                archived
              </span>
            )}
          </div>
          {dashboard.description && (
            <p className="mt-1.5 max-w-3xl text-[13px] leading-5 text-[var(--color-text-muted)]">
              {dashboard.description}
            </p>
          )}
          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-[var(--color-text-dim)]">
            <span data-testid="dashboard-version-line">{versionLine}</span>
            <span aria-hidden="true">·</span>
            <span className="inline-flex items-center gap-1.5">
              <StatusDot
                status={pollError ? "failed" : refreshing ? "running" : (dashboard.last_refresh_status ?? "none")}
              />
              <span
                data-testid="dashboard-refresh-line"
                className={pollError ? "text-[var(--color-error)]" : undefined}
              >
                {pollError ?? (refreshing ? "Refreshing…" : refreshStatusLine(dashboard, { now: now() }))}
              </span>
            </span>
            {dashboard.refresh.interval_minutes != null && (
              <>
                <span aria-hidden="true">·</span>
                <span data-testid="dashboard-schedule-label">{refreshSummary(dashboard.refresh)}</span>
              </>
            )}
            {owner && (
              <>
                <span aria-hidden="true">·</span>
                <span data-testid="dashboard-owner">by {owner}</span>
              </>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canEdit && (
            <button
              type="button"
              data-testid="dashboard-refresh-now"
              disabled={refreshing || busy || archived}
              onClick={actions.onRefreshNow}
              className={PRIMARY_BUTTON_CLASS}
            >
              <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} strokeWidth={1.75} />
              {refreshing ? "Refreshing" : "Refresh now"}
            </button>
          )}
          {canEdit && (
            <button
              type="button"
              data-testid="dashboard-open-settings"
              disabled={busy}
              onClick={actions.onOpenSettings}
              className={BUTTON_CLASS}
            >
              <Settings2 className="h-3.5 w-3.5" strokeWidth={1.5} />
              Settings
            </button>
          )}
          <button
            type="button"
            data-testid="dashboard-edit-in-chat"
            disabled={busy}
            onClick={actions.onEditInChat}
            className={BUTTON_CLASS}
          >
            <MessageSquarePlus className="h-3.5 w-3.5" strokeWidth={1.5} />
            Edit in chat
          </button>
          <button
            type="button"
            data-testid="dashboard-download-json"
            onClick={actions.onDownloadJson}
            className={BUTTON_CLASS}
          >
            <ArrowDownToLine className="h-3.5 w-3.5" strokeWidth={1.5} />
            Download JSON
          </button>
          {canEdit && (
            <>
              <button
                ref={menu.anchorRef}
                type="button"
                aria-label="More actions"
                aria-haspopup="menu"
                aria-expanded={menu.open}
                data-testid="dashboard-more"
                disabled={busy}
                onClick={() => menu.setOpen((value) => !value)}
                className={BUTTON_CLASS}
              >
                <MoreHorizontal className="h-3.5 w-3.5" />
              </button>
              <Menu
                open={menu.open}
                onClose={menu.close}
                anchorRef={menu.anchorRef}
                label="Dashboard actions"
                items={[
                  { label: archived ? "Unarchive" : "Archive", onSelect: actions.onArchiveToggle },
                  { label: "Delete…", onSelect: actions.onDelete, danger: true },
                ]}
              />
            </>
          )}
        </div>
      </div>
    </header>
  );
}
