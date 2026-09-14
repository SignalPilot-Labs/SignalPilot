"use client";

// Small, shared status marks for the dashboards surfaces: the visibility
// chip, the refresh status dot and chip, the version-origin label and the
// button classes every dashboard action reuses.

import { Building2, Lock } from "lucide-react";

import type {
  DashboardRefreshStatus,
  DashboardVersionOrigin,
  DashboardVisibility,
} from "~/lib/api/dashboards";
import { isActiveRefreshStatus } from "~/lib/api/dashboards";
import { dashboardVisibilityOption } from "~/lib/dashboards/options";

const VISIBILITY_ICONS: Record<DashboardVisibility, typeof Lock> = { private: Lock, org: Building2 };

export const BUTTON_CLASS =
  "inline-flex h-8 items-center gap-1.5 rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 text-[12px] text-[var(--color-text-muted)] transition-colors hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)]";

export const PRIMARY_BUTTON_CLASS =
  "inline-flex h-8 items-center gap-1.5 rounded-[10px] bg-[var(--color-text)] px-3 text-[12px] font-medium text-[var(--color-bg)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-bg)]";

export const CHIP_CLASS =
  "inline-flex h-5 items-center gap-1 rounded-full border px-2 text-[10.5px] leading-none tracking-[0.02em]";

export function VisibilityChip({ visibility }: { visibility: DashboardVisibility }) {
  const { label, hint } = dashboardVisibilityOption(visibility);
  const Icon = VISIBILITY_ICONS[visibility];
  return (
    <span
      data-testid="dashboard-visibility-chip"
      data-visibility={visibility}
      title={hint}
      className={`${CHIP_CLASS} border-[var(--color-border)] text-[var(--color-text-muted)]`}
    >
      <Icon className="h-3 w-3" strokeWidth={1.5} />
      {label}
    </span>
  );
}

function refreshStatusTone(status: DashboardRefreshStatus | "none" | null | undefined): string {
  switch (status) {
    case "succeeded":
      return "var(--color-success)";
    case "failed":
      return "var(--color-error)";
    case "running":
    case "queued":
      return "var(--color-warning)";
    default:
      return "var(--color-text-dim)";
  }
}

/** Colored dot: green succeeded, red failed, amber in progress, dim none. */
export function StatusDot({
  status,
  className = "",
}: {
  status: DashboardRefreshStatus | "none" | null | undefined;
  className?: string;
}) {
  const pulse = status != null && status !== "none" && isActiveRefreshStatus(status);
  return (
    <span
      aria-hidden="true"
      data-testid="dashboard-status-dot"
      data-status={status ?? "none"}
      className={`inline-block h-1.5 w-1.5 flex-none rounded-full ${pulse ? "animate-pulse" : ""} ${className}`}
      style={{ backgroundColor: refreshStatusTone(status) }}
    />
  );
}

const STATUS_LABEL: Record<DashboardRefreshStatus, string> = {
  queued: "Queued",
  running: "Running",
  finalizing: "Finalizing",
  succeeded: "Succeeded",
  failed: "Failed",
  skipped: "Skipped",
};

export function RefreshStatusChip({ status }: { status: DashboardRefreshStatus }) {
  const tone = refreshStatusTone(status);
  return (
    <span
      data-testid="dashboard-refresh-status"
      data-status={status}
      className={CHIP_CLASS}
      style={{ borderColor: `color-mix(in srgb, ${tone} 35%, transparent)`, color: tone }}
    >
      <StatusDot status={status} />
      {STATUS_LABEL[status]}
    </span>
  );
}

const ORIGIN_LABEL: Record<DashboardVersionOrigin, string> = {
  publish: "Published from chat",
  refresh: "Refreshed",
  restore: "Restored",
};

export function versionOriginLabel(origin: DashboardVersionOrigin): string {
  return ORIGIN_LABEL[origin];
}

export function CurrentChip() {
  return (
    <span
      data-testid="dashboard-version-current"
      className={`${CHIP_CLASS} border-[var(--color-success)]/40 text-[var(--color-success)]`}
    >
      current
    </span>
  );
}
