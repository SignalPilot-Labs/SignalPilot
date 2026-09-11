// Publish-from-chat form model: the state behind DashboardPublishDialog,
// the request it produces, and the dataset table it shows. Pure functions
// plus the injectable API surface; no React rendering here.

import type { ConversationFileInfo } from "~/lib/api";
import { ApiRequestError } from "~/lib/api/client";
import {
  listDashboards,
  publishDashboard,
  type DashboardRefreshInterval,
  type DashboardRefreshMode,
  type DashboardVisibility,
  type PublishDashboardRequest,
  type PublishedDashboard,
} from "~/lib/api/dashboards";
import { normalizeFileRef, resolveFileRef } from "~/lib/chat-file-refs";
import { browserTimeZone } from "~/lib/dashboards/timezones";
import { anchorTimeProblem } from "~/components/dashboards/anchor-time-field";
import { timeZoneProblem } from "~/components/dashboards/timezone-field";
import { datasetSnapshotPath, isSqlDataset, type DashboardSpec } from "~/dashboard-renderer";

/** The slice of `lib/api/dashboards` the publish flow calls. Injectable so
 * the fixture harness and unit tests can stand in a fake. */
export type DashboardPublishApi = {
  listDashboards: typeof listDashboards;
  publishDashboard: typeof publishDashboard;
};

export const REAL_DASHBOARD_PUBLISH_API: DashboardPublishApi = {
  listDashboards,
  publishDashboard,
};

const DASHBOARD_DEFAULT_ANCHOR_TIME = "06:00";
const DASHBOARD_DEFAULT_INTERVAL: DashboardRefreshInterval = 1440;

/** "new" or the id of an editable dashboard to publish a new version of. */
type PublishTarget = "new" | string;

export type DashboardPublishForm = {
  name: string;
  target: PublishTarget;
  description: string;
  visibility: DashboardVisibility;
  intervalMinutes: DashboardRefreshInterval | null;
  anchorTime: string;
  timezone: string;
  mode: DashboardRefreshMode;
  notifyOnFailure: boolean;
};

/** The form as it opens for a fresh publish of `spec`. */
export function initialPublishForm(
  spec: Pick<DashboardSpec, "title" | "description">,
  options: { timezone?: string } = {},
): DashboardPublishForm {
  return {
    name: spec.title,
    target: "new",
    description: spec.description ?? "",
    visibility: "org",
    intervalMinutes: DASHBOARD_DEFAULT_INTERVAL,
    anchorTime: DASHBOARD_DEFAULT_ANCHOR_TIME,
    timezone: options.timezone ?? browserTimeZone(),
    mode: "sql",
    notifyOnFailure: true,
  };
}

/** Retarget the form at an existing dashboard, adopting its settings so a
 * new version does not silently rewrite them; "new" keeps the field values. */
export function retargetPublishForm(
  form: DashboardPublishForm,
  target: PublishTarget,
  dashboards: readonly PublishedDashboard[],
): DashboardPublishForm {
  if (target === "new") return { ...form, target };
  const existing = dashboards.find((dashboard) => dashboard.id === target);
  if (!existing) return { ...form, target };
  return {
    ...form,
    target,
    name: existing.name,
    description: existing.description ?? "",
    visibility: existing.visibility,
    intervalMinutes: existing.refresh.interval_minutes,
    anchorTime: existing.refresh.anchor_time ?? DASHBOARD_DEFAULT_ANCHOR_TIME,
    timezone: existing.refresh.timezone,
    mode: existing.refresh.mode,
    notifyOnFailure: existing.notify_on_failure,
  };
}


/** Field-level problems that block submit; empty when the form is valid. */
export function publishFormProblems(form: DashboardPublishForm): string[] {
  const problems: string[] = [];
  if (!form.name.trim()) problems.push("Give the dashboard a name.");
  if (form.intervalMinutes != null) {
    // Same wording as the settings drawer: the controls are shared widgets.
    for (const problem of [anchorTimeProblem(form.anchorTime), timeZoneProblem(form.timezone)]) {
      if (problem) problems.push(problem);
    }
  }
  return problems;
}

/** The wire body, exactly per `PublishDashboardRequest`. */
export function buildPublishRequest(form: DashboardPublishForm): PublishDashboardRequest {
  const description = form.description.trim();
  const body: PublishDashboardRequest = {
    name: form.name.trim(),
    visibility: form.visibility,
    refresh: {
      interval_minutes: form.intervalMinutes,
      anchor_time: form.anchorTime.trim() || null,
      timezone: form.timezone.trim() || "UTC",
      mode: form.mode,
    },
    notify_on_failure: form.notifyOnFailure,
  };
  if (description) body.description = description;
  if (form.target !== "new") body.target_dashboard_id = form.target;
  return body;
}

/** A SQL dataset's snapshot is found or missing in the chat; static rows
 * travel inline in the spec. */
type DatasetSnapshotStatus = "inline" | "found" | "missing";

export type PublishDatasetRow = {
  name: string;
  /** The connection the dataset's SQL runs on; null for static rows. */
  connection: string | null;
  /** Scratch-relative snapshot path (`artifacts/datasets/<name>.csv`); null for static rows. */
  path: string | null;
  status: DatasetSnapshotStatus;
  /** The manifest row holding the snapshot, when found. */
  file: ConversationFileInfo | null;
};

/** One row per dataset: kind from the spec, snapshot status from the
 * manifest (the same resolution the viewer uses). */
export function publishDatasetRows(
  spec: DashboardSpec,
  files: readonly ConversationFileInfo[],
  options: { runId?: string | null } = {},
): PublishDatasetRow[] {
  return Object.entries(spec.datasets).map(([name, dataset]) => {
    if (!isSqlDataset(dataset)) {
      return { name, connection: null, path: null, status: "inline", file: null };
    }
    const path = datasetSnapshotPath(name);
    const file = resolveFileRef(normalizeFileRef(path), files, options);
    return {
      name,
      connection: dataset.connection,
      path,
      status: file ? "found" : "missing",
      file,
    };
  });
}

/** "SQL · <connection>" for a SQL dataset, "Static" for inline rows. */
export function datasetKindLabel(row: Pick<PublishDatasetRow, "connection">): string {
  return row.connection === null ? "Static" : `SQL · ${row.connection}`;
}

/** The dashboard already published from this exact chat file, if any. */
export function findPublishedDashboard(
  dashboards: readonly PublishedDashboard[],
  conversationId: string,
  fileId: string,
): PublishedDashboard | null {
  const matches = dashboards.filter(
    (dashboard) =>
      dashboard.source_conversation_id === conversationId &&
      dashboard.source_file_id === fileId &&
      !dashboard.archived_at,
  );
  if (matches.length === 0) return null;
  return [...matches].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
}

const DASHBOARD_FILE_SUFFIX = ".dashboard.json";

/** `revenue.dashboard.json` -> `revenue`; null for any other filename. */
export function dashboardFileStem(filename: string): string | null {
  const base = filename.split("/").pop() ?? filename;
  if (!base.toLowerCase().endsWith(DASHBOARD_FILE_SUFFIX)) return null;
  const stem = base.slice(0, -DASHBOARD_FILE_SUFFIX.length);
  return stem || null;
}

/**
 * The published dashboard this file was loaded from: `dashboard_load_published`
 * writes `artifacts/<slug>.dashboard.json`, so a stem that equals the slug
 * of a dashboard the user can edit is that dashboard. Read-only and
 * archived dashboards never match: the user could not version them.
 */
export function findLoadedDashboard(
  dashboards: readonly PublishedDashboard[],
  filename: string,
): PublishedDashboard | null {
  const stem = dashboardFileStem(filename);
  if (!stem) return null;
  return (
    dashboards.find(
      (dashboard) => dashboard.slug === stem && dashboard.can_edit && !dashboard.archived_at,
    ) ?? null
  );
}

/** Where a chat dashboard file came from, for the strip and the publish
 * target: already published from this exact file, or loaded from the
 * gallery by slug. */
export type DashboardSource = {
  dashboard: PublishedDashboard;
  origin: "published" | "loaded";
};

/** A publish from this conversation+file wins; else the slug match. */
export function resolveDashboardSource(
  dashboards: readonly PublishedDashboard[],
  conversationId: string,
  file: { id: string; filename: string },
): DashboardSource | null {
  const published = findPublishedDashboard(dashboards, conversationId, file.id);
  if (published) return { dashboard: published, origin: "published" };
  const loaded = findLoadedDashboard(dashboards, file.filename);
  return loaded ? { dashboard: loaded, origin: "loaded" } : null;
}

export type PublishErrorInfo = {
  status: number | null;
  message: string;
  /** Per-dataset problems the gateway reported (422): a missing snapshot,
   * columns the SQL does not return, or the SQL error text. */
  datasets: { name: string; problem: string }[];
};

/** True when `text` names `word` as a whole token. */
function mentions(text: string, word: string): boolean {
  const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(^|[^A-Za-z0-9_])${escaped}([^A-Za-z0-9_]|$)`).test(text);
}

function collectStrings(value: unknown): string[] {
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string");
  return [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/**
 * The per-dataset map of the publish gate's 422s:
 * `not_repeatable` -> `{name: {missing_columns: [...]}}`,
 * `sql_failed` -> `{name: "error text"}`.
 */
function datasetProblems(code: string, datasets: unknown): PublishErrorInfo["datasets"] {
  if (!isRecord(datasets)) return [];
  return Object.entries(datasets).map(([name, value]) => {
    if (code === "not_repeatable") {
      const columns = isRecord(value) ? collectStrings(value.missing_columns) : [];
      return { name, problem: columns.length ? `missing columns: ${columns.join(", ")}` : "missing columns" };
    }
    return { name, problem: typeof value === "string" ? value : "the SQL failed" };
  });
}

/**
 * Turns an API failure into something the dialog can show inline. The
 * gateway answers 422 with a `detail` object: `missing_datasets` names
 * snapshots absent from the chat, `code: "not_repeatable"` lists the
 * columns each dataset's SQL does not return, `code: "sql_failed"` carries
 * each dataset's error; 409 is a slug or refresh conflict. `detail` may
 * also be a plain string.
 */
export function describePublishError(error: unknown): PublishErrorInfo {
  const status = error instanceof ApiRequestError ? error.status : null;
  const raw = error instanceof ApiRequestError ? error.body : error instanceof Error ? error.message : String(error);
  let detail: unknown = raw;
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    detail = parsed && typeof parsed === "object" && "detail" in parsed ? parsed.detail : parsed;
  } catch {
    // Plain text body.
  }
  let message = "";
  let missing: string[] = [];
  let datasets: PublishErrorInfo["datasets"] = [];
  if (typeof detail === "string") {
    message = detail;
  } else if (isRecord(detail)) {
    const code = typeof detail.code === "string" ? detail.code : "";
    const text = detail.message ?? detail.error ?? detail.detail;
    message = typeof text === "string" ? text : "";
    if (code === "not_repeatable" || code === "sql_failed") {
      datasets = datasetProblems(code, detail.datasets);
      if (!message) {
        message =
          code === "not_repeatable"
            ? "The SQL of these datasets does not return every column the charts use. Fix the SQL, run sp.dashboard_dataset again, and publish."
            : "The SQL of these datasets failed when the gateway ran it.";
      }
    } else {
      missing = collectStrings(detail.missing_datasets ?? detail.missing ?? detail.datasets);
      datasets = missing.map((name) => ({ name, problem: `no snapshot at ${datasetSnapshotPath(name)}` }));
    }
  }
  if (!message) {
    if (status === 422 && missing.length > 0) {
      message = `The gateway could not find the snapshot of these datasets: ${missing.join(", ")}.`;
    } else if (status === 422) {
      message = "The gateway rejected the dashboard file.";
    } else if (status === 409) {
      message = "That dashboard is busy or its name is taken. Pick another name or try again shortly.";
    } else if (status === 403) {
      message = "You cannot edit that dashboard.";
    } else {
      message = raw || "Publishing failed.";
    }
  } else if (status === 422 && missing.length > 0 && !missing.every((name) => mentions(message, name))) {
    message = `${message} Missing: ${missing.join(", ")}.`;
  }
  return { status, message, datasets };
}
