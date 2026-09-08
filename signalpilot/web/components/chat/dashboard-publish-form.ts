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
import type { DashboardSpec } from "~/dashboard-renderer";

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

export const DASHBOARD_DEFAULT_ANCHOR_TIME = "06:00";
export const DASHBOARD_DEFAULT_INTERVAL: DashboardRefreshInterval = 1440;

/** "new" or the id of an editable dashboard to publish a new version of. */
export type PublishTarget = "new" | string;

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

export type DatasetFileStatus = "inline" | "found" | "missing";

export type PublishDatasetRow = {
  name: string;
  /** True when the spec carries a SQL source the refresh can re-run. */
  refreshable: boolean;
  /** The spec's file reference, when the dataset is file-backed. */
  path: string | null;
  status: DatasetFileStatus;
  /** The manifest row backing the dataset, when found. */
  file: ConversationFileInfo | null;
};

/** One row per dataset: refreshability from the spec, file status from the
 * manifest (the same resolution the viewer uses). */
export function publishDatasetRows(
  spec: DashboardSpec,
  files: readonly ConversationFileInfo[],
  options: { runId?: string | null } = {},
): PublishDatasetRow[] {
  return Object.entries(spec.datasets).map(([name, dataset]) => {
    const refreshable = dataset.source?.kind === "sql";
    if (typeof dataset.file !== "string") {
      return { name, refreshable, path: null, status: "inline", file: null };
    }
    const file = resolveFileRef(normalizeFileRef(dataset.file), files, options);
    return {
      name,
      refreshable,
      path: dataset.file,
      status: file ? "found" : "missing",
      file,
    };
  });
}

export function refreshableLabel(row: Pick<PublishDatasetRow, "refreshable">): string {
  return row.refreshable ? "Refreshable (SQL)" : "Static snapshot";
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

export type PublishErrorInfo = {
  status: number | null;
  message: string;
  /** Dataset names the gateway could not find (422). */
  missing: string[];
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

/**
 * Turns an API failure into something the dialog can show inline. The
 * gateway answers 422 with the missing dataset names and 409 for a slug or
 * refresh conflict; both carry a `detail` that is a string or an object.
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
  if (typeof detail === "string") {
    message = detail;
  } else if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    missing = collectStrings(record.missing_datasets ?? record.missing ?? record.datasets);
    const text = record.message ?? record.error ?? record.detail;
    message = typeof text === "string" ? text : "";
  }
  if (!message) {
    if (status === 422 && missing.length > 0) {
      message = `The gateway could not find these dataset files: ${missing.join(", ")}.`;
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
  return { status, message, missing };
}
