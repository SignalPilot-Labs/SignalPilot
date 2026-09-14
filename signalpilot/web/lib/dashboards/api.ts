// The dashboards API surface the pages and components call. The real
// implementation is `lib/api/dashboards.ts`; the fixture page and the unit
// tests swap in an in-memory one through `DashboardsApiProvider`.

import * as real from "~/lib/api/dashboards";

export type DashboardsApi = {
  listDashboards: typeof real.listDashboards;
  getDashboard: typeof real.getDashboard;
  getDashboardBundle: typeof real.getDashboardBundle;
  updateDashboard: typeof real.updateDashboard;
  refreshDashboardNow: typeof real.refreshDashboardNow;
  listDashboardRefreshes: typeof real.listDashboardRefreshes;
  restoreDashboardVersion: typeof real.restoreDashboardVersion;
  archiveDashboard: typeof real.archiveDashboard;
  unarchiveDashboard: typeof real.unarchiveDashboard;
  deleteDashboard: typeof real.deleteDashboard;
  openDashboardEditChat: typeof real.openDashboardEditChat;
  fetchDashboardDataset: typeof real.fetchDashboardDataset;
};

export const realDashboardsApi: DashboardsApi = {
  listDashboards: real.listDashboards,
  getDashboard: real.getDashboard,
  getDashboardBundle: real.getDashboardBundle,
  updateDashboard: real.updateDashboard,
  refreshDashboardNow: real.refreshDashboardNow,
  listDashboardRefreshes: real.listDashboardRefreshes,
  restoreDashboardVersion: real.restoreDashboardVersion,
  archiveDashboard: real.archiveDashboard,
  unarchiveDashboard: real.unarchiveDashboard,
  deleteDashboard: real.deleteDashboard,
  openDashboardEditChat: real.openDashboardEditChat,
  fetchDashboardDataset: real.fetchDashboardDataset,
};

/** Where the dashboard pages link to; the fixture harness rewrites these. */
export type DashboardsRoutes = {
  gallery: string;
  dashboard: (slug: string) => string;
  chat: (conversationId: string) => string;
};

export const realDashboardsRoutes: DashboardsRoutes = {
  gallery: "/dashboards",
  dashboard: (slug) => `/dashboards/${encodeURIComponent(slug)}`,
  chat: (conversationId) => `/chats/${encodeURIComponent(conversationId)}`,
};
