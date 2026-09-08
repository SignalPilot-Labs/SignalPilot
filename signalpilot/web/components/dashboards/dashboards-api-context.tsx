"use client";

// Dependency seam for the dashboards pages: the API they call and the routes
// they link to. The default is the real gateway client; the fixture page and
// the unit tests provide an in-memory API and rewritten routes.

import { createContext, useContext, useMemo, type ReactNode } from "react";

import {
  realDashboardsApi,
  realDashboardsRoutes,
  type DashboardsApi,
  type DashboardsRoutes,
} from "~/lib/dashboards/api";

export type DashboardsContextValue = {
  api: DashboardsApi;
  routes: DashboardsRoutes;
  /** Clock for relative labels; the fixture pins it so labels are stable. */
  now: () => number;
};

const DashboardsContext = createContext<DashboardsContextValue>({
  api: realDashboardsApi,
  routes: realDashboardsRoutes,
  now: () => Date.now(),
});

export function DashboardsApiProvider({
  api,
  routes,
  now,
  children,
}: {
  api?: DashboardsApi;
  routes?: Partial<DashboardsRoutes>;
  now?: () => number;
  children: ReactNode;
}) {
  const value = useMemo<DashboardsContextValue>(
    () => ({
      api: api ?? realDashboardsApi,
      routes: { ...realDashboardsRoutes, ...routes },
      now: now ?? (() => Date.now()),
    }),
    [api, routes, now],
  );
  return <DashboardsContext.Provider value={value}>{children}</DashboardsContext.Provider>;
}

export function useDashboardsApi(): DashboardsApi {
  return useContext(DashboardsContext).api;
}

export function useDashboardsRoutes(): DashboardsRoutes {
  return useContext(DashboardsContext).routes;
}

export function useDashboardsClock(): () => number {
  return useContext(DashboardsContext).now;
}
