// The option tables the publish dialog, the settings drawer and the gallery
// chips share, so every surface names a visibility or refresh mode the same
// way. The wire values ("org", "sql") never change; only the copy lives here.

import type { DashboardRefreshMode, DashboardVisibility } from "~/lib/api/dashboards";

export type DashboardOption<T extends string> = { value: T; label: string; hint: string };

export const DASHBOARD_VISIBILITY_OPTIONS: DashboardOption<DashboardVisibility>[] = [
  { value: "private", label: "Private", hint: "Only you can open it." },
  { value: "org", label: "Team", hint: "Everyone in your team can open it from the gallery." },
  { value: "link", label: "Link", hint: "Anyone with the share link can open it." },
];

export const DASHBOARD_REFRESH_MODE_OPTIONS: DashboardOption<DashboardRefreshMode>[] = [
  {
    value: "sql",
    label: "SQL re-run",
    hint: "Runs each dataset's saved SQL against its connection. Datasets without SQL keep their last snapshot.",
  },
  {
    value: "agent",
    label: "Agent run",
    hint: "Starts a chat run that rebuilds every dataset, then checks the result before it goes live.",
  },
];

export function dashboardRefreshModeLabel(mode: DashboardRefreshMode): string {
  return DASHBOARD_REFRESH_MODE_OPTIONS.find((option) => option.value === mode)?.label ?? mode;
}

export function dashboardVisibilityOption(visibility: DashboardVisibility): DashboardOption<DashboardVisibility> {
  return DASHBOARD_VISIBILITY_OPTIONS.find((option) => option.value === visibility) ?? DASHBOARD_VISIBILITY_OPTIONS[0];
}
