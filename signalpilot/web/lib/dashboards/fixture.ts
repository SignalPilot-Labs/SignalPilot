// Fixture data for the dashboards test page and the unit tests: one
// published dashboard with three versions and four refreshes, backed by the
// renderer's revenue fixture. Timestamps are relative to FIXTURE_NOW so the
// relative labels are stable across runs.

import revenueSpecJson from "~/dashboard-renderer/fixtures/revenue.dashboard.json";
import { parseDatasetText, validateDashboardSpec, type DashboardSpec, type DatasetRows } from "~/dashboard-renderer";
import type {
  DashboardBundle,
  DashboardDetail,
  DashboardRefresh,
  DashboardVersion,
  PublishedDashboard,
} from "~/lib/api/dashboards";
import {
  DASHBOARD_MONTHLY_CSV_FILE,
  DASHBOARD_REGION_JSON_FILE,
} from "~/lib/chat-test-fixture-dashboard";

/** A fixed "now" (UTC) so every relative label in the fixture is stable. */
export const FIXTURE_NOW = Date.parse("2026-09-08T15:00:00Z");

export const FIXTURE_DASHBOARD_ID = "dash_fixture0000000000000000000001";
export const FIXTURE_DASHBOARD_SLUG = "revenue-overview-2024";
export const FIXTURE_AGENT_CONVERSATION_ID = "conv-fixture-agent-refresh";
export const FIXTURE_USER_ID = "user_fixture_owner";

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const iso = (offsetMs: number) => new Date(FIXTURE_NOW + offsetMs).toISOString();

function loadSpec(): DashboardSpec {
  const result = validateDashboardSpec(revenueSpecJson);
  if (!result.ok) throw new Error(`Fixture spec is invalid: ${result.errors.join("; ")}`);
  return result.spec;
}

export const FIXTURE_SPEC: DashboardSpec = loadSpec();

/** The stored dataset files of every fixture version, as the download route serves them. */
export function fixtureDatasetFiles(): Record<string, { text: string; type: string }> {
  return {
    revenue_monthly: { text: DASHBOARD_MONTHLY_CSV_FILE, type: "text/csv" },
    revenue_by_region: { text: DASHBOARD_REGION_JSON_FILE, type: "application/json" },
  };
}

/** The renderer fixture's two data files plus the inline summary rows. */
export function fixtureDatasets(): Record<string, DatasetRows> {
  return {
    summary: (FIXTURE_SPEC.datasets.summary.rows ?? []) as DatasetRows,
    revenue_monthly: parseDatasetText(DASHBOARD_MONTHLY_CSV_FILE, "revenue_monthly.csv"),
    revenue_by_region: parseDatasetText(DASHBOARD_REGION_JSON_FILE, "revenue_by_region.json"),
  };
}

const DATASET_META = {
  revenue_monthly: { row_count: 48, byte_size: 1_812, filename: "revenue_monthly.csv" },
  revenue_by_region: { row_count: 4, byte_size: 612, filename: "revenue_by_region.json" },
};

export const FIXTURE_VERSION_IDS = {
  v1: "dver_fixture000000000000000000001",
  v2: "dver_fixture000000000000000000002",
  v3: "dver_fixture000000000000000000003",
} as const;

export const FIXTURE_REFRESH_IDS = {
  succeeded: "dref_fixture00000000000000000001",
  failed: "dref_fixture00000000000000000002",
  running: "dref_fixture00000000000000000003",
  skipped: "dref_fixture00000000000000000004",
} as const;

export function fixtureVersions(): DashboardVersion[] {
  const chartCount = FIXTURE_SPEC.charts.length;
  return [
    {
      id: FIXTURE_VERSION_IDS.v3,
      version_no: 3,
      produced_by: "restore",
      producer_ref: FIXTURE_USER_ID,
      chart_count: chartCount,
      dataset_meta: DATASET_META,
      created_at: iso(-2 * HOUR),
    },
    {
      id: FIXTURE_VERSION_IDS.v2,
      version_no: 2,
      produced_by: "refresh",
      producer_ref: FIXTURE_REFRESH_IDS.succeeded,
      chart_count: chartCount,
      dataset_meta: DATASET_META,
      created_at: iso(-1 * DAY - 9 * HOUR),
    },
    {
      id: FIXTURE_VERSION_IDS.v1,
      version_no: 1,
      produced_by: "publish",
      producer_ref: FIXTURE_USER_ID,
      chart_count: chartCount,
      dataset_meta: DATASET_META,
      created_at: iso(-3 * DAY),
    },
  ];
}

export function fixtureRefreshes(): DashboardRefresh[] {
  return [
    {
      id: FIXTURE_REFRESH_IDS.running,
      mode: "agent",
      trigger: "manual",
      status: "running",
      scheduled_for: null,
      started_at: iso(-6 * 60_000),
      finished_at: null,
      version_id: null,
      run_id: "run-fixture-agent-refresh",
      conversation_id: FIXTURE_AGENT_CONVERSATION_ID,
      error: null,
      detail: null,
      created_at: iso(-6 * 60_000),
    },
    {
      id: FIXTURE_REFRESH_IDS.skipped,
      mode: "sql",
      trigger: "schedule",
      status: "skipped",
      scheduled_for: iso(-9 * HOUR),
      started_at: iso(-9 * HOUR),
      finished_at: iso(-9 * HOUR),
      version_id: null,
      run_id: null,
      conversation_id: null,
      error: "refresh already in progress",
      detail: null,
      created_at: iso(-9 * HOUR),
    },
    {
      id: FIXTURE_REFRESH_IDS.failed,
      mode: "sql",
      trigger: "schedule",
      status: "failed",
      scheduled_for: iso(-1 * DAY + 3 * HOUR),
      started_at: iso(-1 * DAY + 3 * HOUR),
      finished_at: iso(-1 * DAY + 3 * HOUR + 47_000),
      version_id: null,
      run_id: null,
      conversation_id: null,
      error:
        "1 of 2 datasets failed: revenue_by_region: column \"region\" is missing from the query result (GovernedQueryError: relation fct_orders does not exist)",
      detail: {
        revenue_monthly: { status: "carried_forward" },
        revenue_by_region: {
          status: "failed",
          error: "relation fct_orders does not exist",
        },
      },
      created_at: iso(-1 * DAY + 3 * HOUR),
    },
    {
      id: FIXTURE_REFRESH_IDS.succeeded,
      mode: "sql",
      trigger: "schedule",
      status: "succeeded",
      scheduled_for: iso(-1 * DAY - 9 * HOUR),
      started_at: iso(-1 * DAY - 9 * HOUR),
      finished_at: iso(-1 * DAY - 9 * HOUR + 12_000),
      version_id: FIXTURE_VERSION_IDS.v2,
      run_id: null,
      conversation_id: null,
      error: null,
      detail: {
        revenue_monthly: { status: "carried_forward" },
        revenue_by_region: { status: "succeeded", row_count: 4 },
      },
      created_at: iso(-1 * DAY - 9 * HOUR),
    },
  ];
}

export function fixtureDashboard(): PublishedDashboard {
  return {
    id: FIXTURE_DASHBOARD_ID,
    slug: FIXTURE_DASHBOARD_SLUG,
    name: FIXTURE_SPEC.title,
    description: FIXTURE_SPEC.description ?? null,
    visibility: "org",
    project_id: "proj-fixture",
    created_by_user_id: FIXTURE_USER_ID,
    created_by_label: "daniel@example.com",
    source_conversation_id: "conv-fixture-source",
    source_file_id: "file-fixture-dashboard",
    current_version_id: FIXTURE_VERSION_IDS.v3,
    current_version_no: 3,
    chart_count: FIXTURE_SPEC.charts.length,
    refresh: {
      interval_minutes: 1440,
      anchor_time: "06:00",
      timezone: "America/New_York",
      mode: "sql",
    },
    notify_on_failure: true,
    next_refresh_at: iso(19 * HOUR),
    last_refresh_at: iso(-1 * DAY - 9 * HOUR),
    last_refresh_status: "succeeded",
    created_at: iso(-3 * DAY),
    updated_at: iso(-2 * HOUR),
    archived_at: null,
    can_edit: true,
  };
}

/** A second, archived dashboard so the gallery's archived filter has work to do. */
export function fixtureArchivedDashboard(): PublishedDashboard {
  return {
    ...fixtureDashboard(),
    id: "dash_fixture0000000000000000000002",
    slug: "churn-watch-q2",
    name: "Churn watch Q2",
    description: "Weekly churn cohorts by plan; retired after the Q3 model rebuild.",
    visibility: "private",
    current_version_id: "dver_fixture0000000000000000000a1",
    current_version_no: 1,
    chart_count: 4,
    refresh: { interval_minutes: null, anchor_time: "06:00", timezone: "UTC", mode: "sql" },
    next_refresh_at: null,
    last_refresh_at: iso(-20 * DAY),
    last_refresh_status: "failed",
    created_at: iso(-40 * DAY),
    updated_at: iso(-20 * DAY),
    archived_at: iso(-19 * DAY),
    can_edit: true,
  };
}

export function fixtureDetail(): DashboardDetail {
  return { dashboard: fixtureDashboard(), versions: fixtureVersions(), refreshes: fixtureRefreshes() };
}

export function fixtureBundle(version = fixtureVersions()[0]): DashboardBundle {
  return { dashboard: fixtureDashboard(), version, spec: FIXTURE_SPEC, datasets: fixtureDatasets() };
}
