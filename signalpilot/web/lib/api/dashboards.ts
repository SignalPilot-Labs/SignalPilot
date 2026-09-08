// Published dashboards: the team gallery, versions, refreshes, and the
// publish action from a chat artifact. The gateway is the source of truth.

import type { DashboardSpec, DatasetRows } from "~/dashboard-renderer";

import { GATEWAY_URL, getAuthHeaders, request } from "./client";

export type DashboardVisibility = "private" | "org";
export type DashboardRefreshMode = "sql" | "agent";
export type DashboardRefreshStatus =
  | "queued"
  | "running"
  | "finalizing"
  | "succeeded"
  | "failed"
  | "skipped";

/** Statuses of a refresh that is still in flight; mirrors the gateway's ACTIVE_REFRESH_STATUSES. */
const DASHBOARD_ACTIVE_REFRESH_STATUSES: readonly DashboardRefreshStatus[] = [
  "queued",
  "running",
  "finalizing",
];

export function isActiveRefreshStatus(status: DashboardRefreshStatus): boolean {
  return DASHBOARD_ACTIVE_REFRESH_STATUSES.includes(status);
}
export type DashboardVersionOrigin = "publish" | "refresh" | "restore";

/** Allowed refresh intervals in minutes; null means off. */
const DASHBOARD_REFRESH_INTERVALS = [15, 60, 120, 240, 480, 720, 1440] as const;
export type DashboardRefreshInterval = (typeof DASHBOARD_REFRESH_INTERVALS)[number];

export type DashboardRefreshSettings = {
  interval_minutes: DashboardRefreshInterval | null;
  /** "HH:MM" 24h wall-clock in `timezone`; the schedule aligns to it. */
  anchor_time: string | null;
  timezone: string;
  mode: DashboardRefreshMode;
};

export type PublishedDashboard = {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  visibility: DashboardVisibility;
  project_id: string | null;
  created_by_user_id: string;
  created_by_label: string;
  source_conversation_id: string | null;
  source_file_id: string | null;
  current_version_id: string | null;
  current_version_no: number | null;
  chart_count: number;
  refresh: DashboardRefreshSettings;
  notify_on_failure: boolean;
  next_refresh_at: string | null;
  last_refresh_at: string | null;
  last_refresh_status: "succeeded" | "failed" | "skipped" | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  can_edit: boolean;
};

export type DashboardDatasetMeta = {
  row_count: number;
  byte_size: number;
  filename: string;
};

export type DashboardVersion = {
  id: string;
  version_no: number;
  produced_by: DashboardVersionOrigin;
  producer_ref: string | null;
  chart_count: number;
  dataset_meta: Record<string, DashboardDatasetMeta>;
  created_at: string;
};

export type DashboardRefresh = {
  id: string;
  mode: DashboardRefreshMode;
  trigger: "schedule" | "manual";
  status: DashboardRefreshStatus;
  scheduled_for: string | null;
  started_at: string | null;
  finished_at: string | null;
  version_id: string | null;
  run_id: string | null;
  conversation_id: string | null;
  error: string | null;
  detail: Record<string, unknown> | null;
  created_at: string;
};

export type DashboardDetail = {
  dashboard: PublishedDashboard;
  versions: DashboardVersion[];
  refreshes: DashboardRefresh[];
};

export type DashboardBundle = {
  dashboard: PublishedDashboard;
  version: DashboardVersion;
  spec: DashboardSpec;
  datasets: Record<string, DatasetRows>;
};

export type PublishDashboardRequest = {
  name: string;
  slug?: string;
  description?: string;
  visibility: DashboardVisibility;
  refresh: DashboardRefreshSettings;
  notify_on_failure?: boolean;
  /** Publish a new version of an existing dashboard instead of creating one. */
  target_dashboard_id?: string;
};

export type UpdateDashboardRequest = {
  name?: string;
  description?: string | null;
  visibility?: DashboardVisibility;
  refresh?: DashboardRefreshSettings;
  notify_on_failure?: boolean;
};

export async function publishDashboard(
  conversationId: string,
  fileId: string,
  body: PublishDashboardRequest,
): Promise<{ dashboard: PublishedDashboard; version: DashboardVersion }> {
  return request(
    `/api/chat/conversations/${encodeURIComponent(conversationId)}/files/${encodeURIComponent(fileId)}/publish-dashboard`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function listDashboards(options?: {
  includeArchived?: boolean;
}): Promise<{ dashboards: PublishedDashboard[] }> {
  const query = options?.includeArchived ? "?include_archived=true" : "";
  return request(`/api/dashboards${query}`);
}

export async function getDashboard(idOrSlug: string): Promise<DashboardDetail> {
  return request(`/api/dashboards/${encodeURIComponent(idOrSlug)}`);
}

export async function getDashboardBundle(
  dashboardId: string,
  versionId: string,
): Promise<DashboardBundle> {
  return request(
    `/api/dashboards/${encodeURIComponent(dashboardId)}/versions/${encodeURIComponent(versionId)}/bundle`,
  );
}

/** Fetch a version's stored dataset file with auth headers (for downloads). */
export async function fetchDashboardDataset(
  dashboardId: string,
  versionId: string,
  name: string,
): Promise<Blob> {
  const headers = await getAuthHeaders();
  const response = await fetch(
    `${GATEWAY_URL}/api/dashboards/${encodeURIComponent(dashboardId)}/versions/${encodeURIComponent(versionId)}/datasets/${encodeURIComponent(name)}`,
    { headers },
  );
  if (!response.ok) throw new Error(`Download failed (${response.status})`);
  return response.blob();
}

export async function updateDashboard(
  dashboardId: string,
  body: UpdateDashboardRequest,
): Promise<{ dashboard: PublishedDashboard }> {
  return request(`/api/dashboards/${encodeURIComponent(dashboardId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function refreshDashboardNow(
  dashboardId: string,
): Promise<{ refresh: DashboardRefresh }> {
  return request(`/api/dashboards/${encodeURIComponent(dashboardId)}/refresh`, {
    method: "POST",
  });
}

export async function listDashboardRefreshes(
  dashboardId: string,
  limit = 20,
): Promise<{ refreshes: DashboardRefresh[] }> {
  return request(
    `/api/dashboards/${encodeURIComponent(dashboardId)}/refreshes?limit=${limit}`,
  );
}

export async function restoreDashboardVersion(
  dashboardId: string,
  versionId: string,
): Promise<{ dashboard: PublishedDashboard; version: DashboardVersion }> {
  return request(
    `/api/dashboards/${encodeURIComponent(dashboardId)}/versions/${encodeURIComponent(versionId)}/restore`,
    { method: "POST" },
  );
}

export async function archiveDashboard(
  dashboardId: string,
): Promise<{ dashboard: PublishedDashboard }> {
  return request(`/api/dashboards/${encodeURIComponent(dashboardId)}/archive`, {
    method: "POST",
  });
}

export async function unarchiveDashboard(
  dashboardId: string,
): Promise<{ dashboard: PublishedDashboard }> {
  return request(`/api/dashboards/${encodeURIComponent(dashboardId)}/unarchive`, {
    method: "POST",
  });
}

export async function deleteDashboard(dashboardId: string): Promise<void> {
  await request(`/api/dashboards/${encodeURIComponent(dashboardId)}`, {
    method: "DELETE",
  });
}

export async function openDashboardEditChat(
  dashboardId: string,
): Promise<{ conversation_id: string }> {
  return request(`/api/dashboards/${encodeURIComponent(dashboardId)}/edit-chat`, {
    method: "POST",
  });
}

export const DASHBOARD_REFRESH_OPTIONS: { value: DashboardRefreshInterval | null; label: string }[] = [
  { value: null, label: "Off" },
  { value: 15, label: "Every 15 minutes" },
  { value: 60, label: "Every hour" },
  { value: 120, label: "Every 2 hours" },
  { value: 240, label: "Every 4 hours" },
  { value: 480, label: "Every 8 hours" },
  { value: 720, label: "Every 12 hours" },
  { value: 1440, label: "Daily" },
];
