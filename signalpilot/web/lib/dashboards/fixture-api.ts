// In-memory implementation of the dashboards API for the /dashboards/test
// page and unit tests. State is mutable so settings, restores, refreshes
// and archiving behave like the gateway; a manual refresh completes on a
// timer so the page's 5 s polling has something to observe.

import type {
  DashboardBundle,
  DashboardRefresh,
  DashboardVersion,
  PublishedDashboard,
  UpdateDashboardRequest,
} from "~/lib/api/dashboards";
import { isActiveRefreshStatus } from "~/lib/api/dashboards";
import { ApiRequestError } from "~/lib/api/client";

import type { DashboardsApi } from "./api";
import {
  FIXTURE_NOW,
  FIXTURE_SPEC,
  fixtureArchivedDashboard,
  fixtureDashboard,
  fixtureDatasetFiles,
  fixtureDatasets,
  fixtureRefreshes,
  fixtureVersions,
} from "./fixture";

export type FixtureDashboardsOptions = {
  /** Simulated network latency per call. */
  latencyMs?: number;
  /** How long a manual refresh stays "running" before it succeeds. */
  refreshDurationMs?: number;
  /**
   * The fixture ships with a running agent-mode refresh; it succeeds this
   * long after the API is created so the page's polling has a resolution
   * to observe. 0 keeps it running forever.
   */
  agentRefreshCompletesMs?: number;
  /** Clock for new timestamps; defaults to the fixture's frozen now. */
  now?: () => number;
};

type State = {
  dashboards: PublishedDashboard[];
  versions: Map<string, DashboardVersion[]>;
  refreshes: Map<string, DashboardRefresh[]>;
};

let sequence = 0;
const nextId = (prefix: string) => `${prefix}_fixture_${String(++sequence).padStart(4, "0")}`;

function initialState(): State {
  const primary = fixtureDashboard();
  const archived = fixtureArchivedDashboard();
  return {
    dashboards: [primary, archived],
    versions: new Map([
      [primary.id, fixtureVersions()],
      [
        archived.id,
        [
          {
            id: archived.current_version_id ?? "",
            version_no: 1,
            produced_by: "publish",
            producer_ref: archived.created_by_user_id,
            chart_count: archived.chart_count,
            dataset_meta: {},
            created_at: archived.created_at,
          },
        ],
      ],
    ]),
    refreshes: new Map([
      [primary.id, fixtureRefreshes()],
      [archived.id, []],
    ]),
  };
}

export function createFixtureDashboardsApi(options: FixtureDashboardsOptions = {}): DashboardsApi & {
  /** Test hook: the mutable state behind the API. */
  state: State;
} {
  const latency = options.latencyMs ?? 0;
  const refreshDuration = options.refreshDurationMs ?? 1_500;
  const now = options.now ?? (() => FIXTURE_NOW);
  const agentCompletesMs = options.agentRefreshCompletesMs ?? 20_000;
  const createdAt = Date.now();
  const state = initialState();

  /** Finalize the seeded running agent refresh once its window has passed. */
  const settleAgentRefresh = () => {
    if (agentCompletesMs <= 0 || Date.now() - createdAt < agentCompletesMs) return;
    for (const dashboard of state.dashboards) {
      const running = (state.refreshes.get(dashboard.id) ?? []).find(
        (r) => r.mode === "agent" && r.status === "running",
      );
      if (!running) continue;
      const version = addVersion(dashboard, "refresh", running.id, versionsOf(dashboard.id)[0]);
      running.status = "succeeded";
      running.finished_at = new Date(now()).toISOString();
      running.version_id = version.id;
      dashboard.last_refresh_at = running.finished_at;
      dashboard.last_refresh_status = "succeeded";
    }
  };

  const wait = <T>(value: T): Promise<T> =>
    latency > 0 ? new Promise((resolve) => setTimeout(() => resolve(value), latency)) : Promise.resolve(value);

  const find = (idOrSlug: string): PublishedDashboard => {
    const found = state.dashboards.find((d) => d.id === idOrSlug || d.slug === idOrSlug);
    if (!found) throw new ApiRequestError(404, `Dashboard not found: ${idOrSlug}`);
    return found;
  };
  const versionsOf = (id: string) => state.versions.get(id) ?? [];
  const refreshesOf = (id: string) => state.refreshes.get(id) ?? [];
  const touch = (dashboard: PublishedDashboard) => {
    dashboard.updated_at = new Date(now()).toISOString();
  };
  const addVersion = (
    dashboard: PublishedDashboard,
    produced_by: DashboardVersion["produced_by"],
    producer_ref: string,
    from: DashboardVersion,
  ): DashboardVersion => {
    const list = versionsOf(dashboard.id);
    const version: DashboardVersion = {
      id: nextId("dver"),
      version_no: (list[0]?.version_no ?? 0) + 1,
      produced_by,
      producer_ref,
      chart_count: from.chart_count,
      dataset_meta: from.dataset_meta,
      created_at: new Date(now()).toISOString(),
    };
    list.unshift(version);
    state.versions.set(dashboard.id, list);
    dashboard.current_version_id = version.id;
    dashboard.current_version_no = version.version_no;
    touch(dashboard);
    return version;
  };

  const bundleFor = (dashboard: PublishedDashboard, version: DashboardVersion): DashboardBundle => ({
    dashboard: { ...dashboard },
    version,
    spec: FIXTURE_SPEC,
    datasets: fixtureDatasets(),
  });

  return {
    state,
    async listDashboards(opts) {
      const rows = state.dashboards
        .filter((d) => opts?.includeArchived || !d.archived_at)
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
        .map((d) => ({ ...d }));
      return wait({ dashboards: rows });
    },
    async getDashboard(idOrSlug) {
      settleAgentRefresh();
      const dashboard = find(idOrSlug);
      return wait({
        dashboard: { ...dashboard },
        versions: versionsOf(dashboard.id).map((v) => ({ ...v })),
        refreshes: refreshesOf(dashboard.id).slice(0, 20).map((r) => ({ ...r })),
      });
    },
    async getDashboardBundle(dashboardId, versionId) {
      const dashboard = find(dashboardId);
      const version = versionsOf(dashboard.id).find((v) => v.id === versionId);
      if (!version) throw new ApiRequestError(404, `Version not found: ${versionId}`);
      return wait(bundleFor(dashboard, version));
    },
    async updateDashboard(dashboardId, body: UpdateDashboardRequest) {
      const dashboard = find(dashboardId);
      if (body.name !== undefined) dashboard.name = body.name;
      if (body.description !== undefined) dashboard.description = body.description;
      if (body.visibility !== undefined) dashboard.visibility = body.visibility;
      if (body.notify_on_failure !== undefined) dashboard.notify_on_failure = body.notify_on_failure;
      if (body.refresh !== undefined) {
        dashboard.refresh = { ...body.refresh };
        dashboard.next_refresh_at =
          body.refresh.interval_minutes == null
            ? null
            : new Date(now() + body.refresh.interval_minutes * 60_000).toISOString();
      }
      touch(dashboard);
      return wait({ dashboard: { ...dashboard } });
    },
    async refreshDashboardNow(dashboardId) {
      const dashboard = find(dashboardId);
      const list = refreshesOf(dashboard.id);
      if (list.some((r) => isActiveRefreshStatus(r.status))) {
        throw new ApiRequestError(409, "A refresh is already queued or running.");
      }
      const startedAt = new Date(now()).toISOString();
      const refresh: DashboardRefresh = {
        id: nextId("dref"),
        mode: dashboard.refresh.mode,
        trigger: "manual",
        status: "running",
        scheduled_for: null,
        started_at: startedAt,
        finished_at: null,
        version_id: null,
        run_id: null,
        conversation_id: null,
        error: null,
        detail: null,
        created_at: startedAt,
      };
      list.unshift(refresh);
      state.refreshes.set(dashboard.id, list);
      setTimeout(() => {
        const current = versionsOf(dashboard.id)[0];
        const version = addVersion(dashboard, "refresh", refresh.id, current);
        refresh.status = "succeeded";
        refresh.finished_at = new Date(now() + refreshDuration).toISOString();
        refresh.version_id = version.id;
        refresh.detail = { revenue_by_region: { status: "succeeded", row_count: 4 } };
        dashboard.last_refresh_at = refresh.finished_at;
        dashboard.last_refresh_status = "succeeded";
      }, refreshDuration);
      return wait({ refresh: { ...refresh } });
    },
    async listDashboardRefreshes(dashboardId, limit = 20) {
      settleAgentRefresh();
      const dashboard = find(dashboardId);
      return wait({ refreshes: refreshesOf(dashboard.id).slice(0, limit).map((r) => ({ ...r })) });
    },
    async restoreDashboardVersion(dashboardId, versionId) {
      const dashboard = find(dashboardId);
      const source = versionsOf(dashboard.id).find((v) => v.id === versionId);
      if (!source) throw new ApiRequestError(404, `Version not found: ${versionId}`);
      const version = addVersion(dashboard, "restore", dashboard.created_by_user_id, source);
      return wait({ dashboard: { ...dashboard }, version });
    },
    async archiveDashboard(dashboardId) {
      const dashboard = find(dashboardId);
      dashboard.archived_at = new Date(now()).toISOString();
      touch(dashboard);
      return wait({ dashboard: { ...dashboard } });
    },
    async unarchiveDashboard(dashboardId) {
      const dashboard = find(dashboardId);
      dashboard.archived_at = null;
      touch(dashboard);
      return wait({ dashboard: { ...dashboard } });
    },
    async deleteDashboard(dashboardId) {
      const dashboard = find(dashboardId);
      state.dashboards = state.dashboards.filter((d) => d.id !== dashboard.id);
      await wait(undefined);
    },
    async openDashboardEditChat(dashboardId) {
      find(dashboardId);
      return wait({ conversation_id: "conv-fixture-edit-chat" });
    },
    async fetchDashboardDataset(dashboardId, versionId, name) {
      const dashboard = find(dashboardId);
      const version = versionsOf(dashboard.id).find((v) => v.id === versionId);
      const file = fixtureDatasetFiles()[name];
      if (!version || !(name in version.dataset_meta) || !file) {
        throw new ApiRequestError(404, `Dataset not found: ${name}`);
      }
      return wait(new Blob([file.text], { type: file.type }));
    },
  };
}
