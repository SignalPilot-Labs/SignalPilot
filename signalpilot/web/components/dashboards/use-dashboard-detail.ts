"use client";

// Data hook for one published dashboard: loads the detail then the live
// bundle, exposes a reload, and polls the refresh list every 5 s while a
// refresh is queued or running so the page can swap to the new version
// the moment it lands.
//
// Two guards keep the page honest: a load generation so a slow, older
// `load()` can never overwrite a newer one, and a polling budget so the
// header never sits on "Refreshing…" after the gateway stopped answering.

import { useCallback, useEffect, useRef, useState } from "react";

import type {
  DashboardBundle,
  DashboardDetail,
  DashboardRefresh,
  PublishedDashboard,
} from "~/lib/api/dashboards";
import { isActiveRefreshStatus } from "~/lib/api/dashboards";
import { requestErrorStatus, userFacingErrorMessage } from "~/lib/api/client";

import { useDashboardsApi } from "./dashboards-api-context";

export const REFRESH_POLL_MS = 5_000;
/** Consecutive poll failures tolerated before polling stops. */
export const REFRESH_POLL_MAX_FAILURES = 3;
/** Statuses that end polling on the first failure: the caller lost access. */
const POLL_FATAL_STATUSES = new Set([401, 403, 404]);

export const POLL_STOPPED_MESSAGE = "Lost track of the refresh; reload the page to see its outcome.";

type DashboardDetailState =
  | { phase: "loading" }
  | { phase: "error"; message: string; notFound: boolean }
  | { phase: "ready"; detail: DashboardDetail; bundle: DashboardBundle | null; bundleError: string | null };

function isActiveRefresh(refresh: DashboardRefresh): boolean {
  return isActiveRefreshStatus(refresh.status);
}

/** Whether a poll failure ends polling: fatal status, or the budget is spent. */
export function pollShouldStop(error: unknown, consecutiveFailures: number): boolean {
  const status = requestErrorStatus(error);
  if (status !== null && POLL_FATAL_STATUSES.has(status)) return true;
  return consecutiveFailures >= REFRESH_POLL_MAX_FAILURES;
}

export function useDashboardDetail(idOrSlug: string) {
  const api = useDashboardsApi();
  const [state, setState] = useState<DashboardDetailState>({ phase: "loading" });
  const bundleVersionRef = useRef<string | null>(null);
  // Bumped on every load; a load whose generation is stale drops its result.
  const generationRef = useRef(0);
  const [pollError, setPollError] = useState<string | null>(null);

  const load = useCallback(
    async (options: { keepBundle?: boolean } = {}) => {
      const generation = ++generationRef.current;
      const isCurrent = () => generationRef.current === generation;
      let detail: DashboardDetail;
      try {
        detail = await api.getDashboard(idOrSlug);
      } catch (error) {
        if (!isCurrent()) return null;
        const fallback = "Could not load this dashboard.";
        setState({
          phase: "error",
          message: userFacingErrorMessage(error, fallback) ?? fallback,
          notFound: requestErrorStatus(error) === 404,
        });
        return null;
      }
      if (!isCurrent()) return null;
      const versionId = detail.dashboard.current_version_id;
      const bundleIsCurrent = options.keepBundle && bundleVersionRef.current === versionId;
      let bundle: DashboardBundle | null = null;
      let bundleError: string | null = null;
      if (!bundleIsCurrent && versionId) {
        try {
          bundle = await api.getDashboardBundle(detail.dashboard.id, versionId);
        } catch (error) {
          const fallback = "Could not load the dashboard data.";
          bundleError = userFacingErrorMessage(error, fallback) ?? fallback;
        }
        if (!isCurrent()) return null;
        bundleVersionRef.current = bundle ? versionId : null;
      }
      setPollError(null);
      setState((prev) => ({
        phase: "ready",
        detail,
        bundle: bundleIsCurrent && prev.phase === "ready" ? prev.bundle : bundle,
        bundleError: bundleIsCurrent && prev.phase === "ready" ? prev.bundleError : bundleError,
      }));
      return detail;
    },
    [api, idOrSlug],
  );

  useEffect(() => {
    bundleVersionRef.current = null;
    setState({ phase: "loading" });
    setPollError(null);
    void load();
    return () => {
      // Unmount or a new target: whatever is in flight must not land.
      generationRef.current += 1;
    };
  }, [load]);

  /** Patch the dashboard record in place (after PATCH/archive/restore). */
  const applyDashboard = useCallback((dashboard: PublishedDashboard) => {
    setState((prev) =>
      prev.phase === "ready" ? { ...prev, detail: { ...prev.detail, dashboard } } : prev,
    );
  }, []);

  /** Put a freshly created refresh at the top of the list (starts polling). */
  const prependRefresh = useCallback((refresh: DashboardRefresh) => {
    setPollError(null);
    setState((prev) =>
      prev.phase === "ready"
        ? { ...prev, detail: { ...prev.detail, refreshes: [refresh, ...prev.detail.refreshes] } }
        : prev,
    );
  }, []);

  const detail = state.phase === "ready" ? state.detail : null;
  const activeRefreshId = detail?.refreshes.find(isActiveRefresh)?.id ?? null;
  const dashboardId = detail?.dashboard.id ?? null;

  useEffect(() => {
    if (!activeRefreshId || !dashboardId || pollError) return;
    let cancelled = false;
    let failures = 0;
    const tick = async () => {
      try {
        const { refreshes } = await api.listDashboardRefreshes(dashboardId, 20);
        if (cancelled) return;
        failures = 0;
        const tracked = refreshes.find((r) => r.id === activeRefreshId);
        if (tracked && isActiveRefresh(tracked)) {
          setState((prev) =>
            prev.phase === "ready" ? { ...prev, detail: { ...prev.detail, refreshes } } : prev,
          );
          return;
        }
        // Terminal (or gone): reload the detail and the bundle for the new version.
        await load({ keepBundle: true });
      } catch (error) {
        if (cancelled) return;
        failures += 1;
        // Setting the error re-runs this effect, whose cleanup clears the timer.
        if (pollShouldStop(error, failures)) setPollError(POLL_STOPPED_MESSAGE);
      }
    };
    const interval = window.setInterval(() => void tick(), REFRESH_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [api, activeRefreshId, dashboardId, load, pollError]);

  return {
    state,
    reload: load,
    applyDashboard,
    prependRefresh,
    /** A refresh is in progress and we are still tracking it. */
    refreshing: activeRefreshId !== null && pollError === null,
    /** Set once polling gave up; cleared by the next reload or refresh. */
    pollError,
  };
}
