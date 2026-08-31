// Data Chat artifact library and saved reports.

import { downloadChatArtifact, request } from "./client";

// Data Chat artifact library and immutable saved reports.
export type ChatReportFreshness = "fresh" | "changes_detected" | "unknown";

export type ChatReportMention = {
  report_id: string;
  title: string;
  kind: "table" | "chart" | "report";
  project_id: string;
  current_version_id: string;
};

export type ChatReportSuggestion = {
  action: "create" | "update" | "open";
  artifact_id: string;
  title: string;
  reason: string;
  report_id: string | null;
  expected_current_version_id: string | null;
  catalog_revision: string | null;
  approval?: {
    status: "created" | "updated" | "existing" | "opened";
    report_id: string;
    version_id: string;
    approved_at: string;
  };
};

export type ChatLibraryArtifactHistoryItem = {
  id: string;
  kind: "table" | "chart" | "report";
  filename: string;
  created_at: string;
  freshness_state: ChatReportFreshness;
  freshness_at: string | null;
  freshness_checked_at: string;
  saved_report_id: string | null;
  saved_version_id: string | null;
  snapshot: Record<string, unknown>;
  download_formats: string[];
};

export type ChatLibraryArtifact = ChatLibraryArtifactHistoryItem & {
  project_id: string | null;
  project_name: string | null;
  original_thread_id: string;
  original_thread_title: string;
  history: ChatLibraryArtifactHistoryItem[];
};

export type ChatLibraryReport = {
  id: string;
  report_id: string | null;
  title: string;
  kind: "table" | "chart" | "report";
  filename: string;
  is_shared: boolean;
  project_id: string | null;
  project_name: string | null;
  original_thread_id: string | null;
  original_thread_title: string | null;
  version_id: string;
  version_ordinal: number;
  freshness_state: ChatReportFreshness;
  freshness_at: string | null;
  freshness_checked_at: string;
  updated_at: string;
  snapshot: Record<string, unknown>;
  download_url: string;
};

export type ChatLibraryResponse = {
  artifacts: { items: ChatLibraryArtifact[]; next_cursor: string | null };
  reports: { items: ChatLibraryReport[]; next_cursor: string | null };
  facets: {
    artifact_types: string[];
    projects: Array<{ id: string; name: string }>;
    original_threads: Array<{ id: string; title: string }>;
  };
};

export type SavedReportVersion = {
  id: string;
  ordinal: number;
  kind: "table" | "chart" | "report";
  filename: string;
  content_hash: string;
  freshness_state: ChatReportFreshness;
  freshness_at: string | null;
  freshness_checked_at: string;
  dbt_commit_sha: string | null;
  schema_fingerprint: string | null;
  published_at: string;
  snapshot: Record<string, unknown>;
  download_url: string;
};

export type SavedReportDetail = {
  id: string;
  title: string;
  kind: "table" | "chart" | "report";
  project_id: string;
  project_name: string | null;
  original_thread_id: string;
  original_thread_title: string;
  current_version_id: string;
  revision: number;
  created_at: string;
  updated_at: string;
  current_version: SavedReportVersion;
  versions: SavedReportVersion[];
  active_share_version_ids: string[];
  refresh: {
    id: string;
    base_version_id: string;
    status: "refreshing" | "update_available" | "failed" | "current";
    drift_state: "none" | "drift" | "unknown";
    explanation: string;
    checked_at: string;
    run_id: string | null;
    conversation_id: string | null;
    candidate_artifact_ids: string[];
  } | null;
};

export type SharedSavedReport = {
  title: string;
  kind: "table" | "chart" | "report";
  version: Omit<
    SavedReportVersion,
    "content_hash" | "dbt_commit_sha" | "schema_fingerprint"
  >;
  shared_at: string;
};

export type ChatLibraryFilters = {
  search?: string;
  kind?: string;
  project_id?: string;
  original_thread_id?: string;
  created_from?: string;
  created_to?: string;
  freshness?: string;
  saved?: string;
  artifact_cursor?: string;
  report_cursor?: string;
  limit?: string;
};

export const getChatLibrary = (filters: ChatLibraryFilters = {}) => {
  const params = new URLSearchParams(
    Object.entries(filters).filter(([, value]) => Boolean(value)) as [
      string,
      string,
    ][],
  );
  return request<ChatLibraryResponse>(
    `/api/chat/library${params.size ? `?${params}` : ""}`,
  );
};

export const getChatReportMentions = (projectId: string, search = "") => {
  const params = new URLSearchParams({ project_id: projectId });
  if (search) params.set("search", search);
  return request<{ items: ChatReportMention[] }>(
    `/api/chat/report-mentions?${params}`,
  );
};

export const approveChatReportSuggestion = (messageId: string) =>
  request<{
    status: "created" | "updated" | "existing" | "opened";
    report_id: string;
    version_id: string;
  }>(`/api/chat/report-suggestions/${encodeURIComponent(messageId)}/approve`, {
    method: "POST",
  });

export const promoteChatArtifact = (artifactId: string, title: string) =>
  request<{
    status: "created" | "existing" | "updated";
    report_id: string;
    version_id: string;
  }>("/api/chat/reports", {
    method: "POST",
    body: JSON.stringify({ artifact_id: artifactId, title }),
  });

export const getSavedChatReport = (reportId: string) =>
  request<SavedReportDetail>(
    `/api/chat/reports/${encodeURIComponent(reportId)}`,
  );

export const publishSavedChatReportVersion = (
  reportId: string,
  artifactId: string,
  expectedCurrentVersionId: string,
) =>
  request<{
    status: "created" | "existing";
    report_id: string;
    version_id: string;
    current_version_id: string;
  }>(`/api/chat/reports/${encodeURIComponent(reportId)}/versions`, {
    method: "POST",
    body: JSON.stringify({
      artifact_id: artifactId,
      expected_current_version_id: expectedCurrentVersionId,
    }),
  });

export const refreshSavedChatReport = (reportId: string) =>
  request<{
    refresh_id: string;
    report_id: string;
    version_id: string;
    conversation_id: string;
    run_id: string | null;
    status: string;
    drift_state: string;
    explanation: string;
    checked_at: string;
  }>(`/api/chat/reports/${encodeURIComponent(reportId)}/refreshes`, {
    method: "POST",
  });

export const shareSavedChatReportVersion = (versionId: string) =>
  request<{ token: string; version_id: string; created_at: string }>(
    `/api/chat/report-versions/${encodeURIComponent(versionId)}/share`,
    { method: "POST" },
  );

export const revokeSavedChatReportVersionShare = (versionId: string) =>
  request<void>(
    `/api/chat/report-versions/${encodeURIComponent(versionId)}/share`,
    { method: "DELETE" },
  );

export const getSharedSavedChatReport = (token: string) =>
  request<SharedSavedReport>(
    `/api/chat/shared-reports/${encodeURIComponent(token)}`,
  );

export async function downloadSavedReportVersion(
  versionId: string,
  format: string,
  filename: string,
): Promise<void> {
  return downloadChatArtifact(
    `/api/chat/report-versions/${encodeURIComponent(versionId)}/download?format=${encodeURIComponent(format)}`,
    format,
    filename,
  );
}
