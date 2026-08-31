// Knowledge base, rendered reports, Notion, Slack, and organization secrets.

import { request } from "./client";

// Knowledge Base
import type {
  KnowledgeDoc,
  KnowledgeEdit,
  KnowledgeUsage,
  RetrievalStats,
} from "../types";

export const listKnowledge = (params?: {
  scope?: string;
  scope_ref?: string;
  category?: string;
  status?: string;
}) => {
  const qs = params
    ? new URLSearchParams(
        Object.entries(params).filter(([, v]) => v !== undefined) as [
          string,
          string,
        ][],
      ).toString()
    : "";
  return request<KnowledgeDoc[]>(`/api/knowledge${qs ? `?${qs}` : ""}`);
};
export const getKnowledgeUsage = () =>
  request<KnowledgeUsage>("/api/knowledge/usage");
export const getKnowledgeRetrievals = (sinceDays = 30) =>
  request<RetrievalStats>(`/api/knowledge/retrievals?since_days=${sinceDays}`);
export const getKnowledgeDoc = (id: string) =>
  request<KnowledgeDoc>(`/api/knowledge/${id}`);
export const createKnowledgeDoc = (payload: {
  scope: KnowledgeDoc["scope"];
  scope_ref: string | null;
  category: KnowledgeDoc["category"];
  title: string;
  body: string;
  status?: KnowledgeDoc["status"];
}) =>
  request<KnowledgeDoc>("/api/knowledge", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const updateKnowledgeDoc = (id: string, body: string) =>
  request<KnowledgeDoc>(`/api/knowledge/${id}`, {
    method: "PUT",
    body: JSON.stringify({ body }),
  });
export const archiveKnowledgeDoc = (id: string) =>
  request<void>(`/api/knowledge/${id}`, { method: "DELETE" });
export const approveKnowledgeDoc = (id: string) =>
  request<KnowledgeDoc>(`/api/knowledge/${id}/approve`, { method: "POST" });
export const listKnowledgeEdits = (id: string, limit = 20) =>
  request<KnowledgeEdit[]>(`/api/knowledge/${id}/edits?limit=${limit}`);

// The following functions support rendered HTML reports.
import type { Report, ReportSummary } from "../types";

export const listReports = (params?: { scope_ref?: string }) => {
  const qs = params?.scope_ref
    ? `?scope_ref=${encodeURIComponent(params.scope_ref)}`
    : "";
  return request<ReportSummary[]>(`/api/reports${qs}`);
};
export const getReport = (id: string) => request<Report>(`/api/reports/${id}`);
export const createReport = (payload: {
  title: string;
  html: string;
  scope_ref?: string | null;
}) =>
  request<Report>("/api/reports", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const deleteReport = (id: string) =>
  request<void>(`/api/reports/${id}`, { method: "DELETE" });

// Notion Integrations
export type NotionIntegration = {
  id: string;
  name: string;
  search_page_ids: string[];
  report_parent_page_id: string | null;
  status: string;
  created_at: number;
  org_id: string | null;
};
export type NotionOAuthInstallationConfig = {
  parent_page_id: string | null;
  trigger_page_id: string | null;
  requests_data_source_id: string | null;
  requests_database_page_id: string | null;
  enabled: boolean;
  default_project_id: string | null;
  default_branch: string;
  analysis_branch_mode: "per_request" | "default_branch";
};
export type NotionOAuthInstallation = {
  id: string;
  workspace_id: string;
  workspace_name: string | null;
  bot_id: string;
  owner_user_id: string | null;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  org_id: string | null;
  config: NotionOAuthInstallationConfig | null;
};
export type NotionPageOption = {
  id: string;
  title: string;
  url: string | null;
};
export type OrgSecretsResponse = {
  has_key: boolean;
  key_preview: string | null;
  updated_at: number | null;
};
export type OrgSecretsUpdate = {
  anthropic_api_key: string | null;
};
export const getOrgSecrets = () =>
  request<OrgSecretsResponse>("/api/org/secrets");
export const updateOrgSecrets = (payload: OrgSecretsUpdate) =>
  request<OrgSecretsResponse>("/api/org/secrets", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
export const getNotionIntegrations = () =>
  request<NotionIntegration[]>("/api/integrations/notion");
export const createNotionIntegration = (payload: {
  name: string;
  api_key: string;
  search_page_ids: string[];
  report_parent_page_id?: string;
}) =>
  request<NotionIntegration>("/api/integrations/notion", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const updateNotionIntegration = (
  name: string,
  updates: Record<string, unknown>,
) =>
  request<NotionIntegration>(`/api/integrations/notion/${name}`, {
    method: "PUT",
    body: JSON.stringify(updates),
  });
export const deleteNotionIntegration = (name: string) =>
  request<void>(`/api/integrations/notion/${name}`, { method: "DELETE" });
export const testNotionIntegration = (name: string) =>
  request<{ status: string; message: string }>(
    `/api/integrations/notion/${name}/test`,
    { method: "POST" },
  );
export const startNotionOAuth = (redirectAfter?: string) => {
  const qs = redirectAfter
    ? `?redirect_after=${encodeURIComponent(redirectAfter)}`
    : "";
  return request<{ authorize_url: string; state: string }>(
    `/api/integrations/notion/oauth/start${qs}`,
  );
};
export const getNotionOAuthInstallations = () =>
  request<NotionOAuthInstallation[]>(
    "/api/integrations/notion/oauth/installations",
  );
export const getNotionOAuthPages = (installationId: string, query?: string) => {
  const qs = query ? `?query=${encodeURIComponent(query)}` : "";
  return request<NotionPageOption[]>(
    `/api/integrations/notion/oauth/${installationId}/pages${qs}`,
  );
};
export type NotionProvisionPayload = {
  sibling_page_id?: string | null;
  parent_page_id?: string | null;
  default_project_id?: string | null;
  default_branch?: string;
  analysis_branch_mode?: "per_request" | "default_branch";
};
export const provisionNotionOAuthInstallation = (
  installationId: string,
  payload: NotionProvisionPayload | string | null = {},
) => {
  const body =
    typeof payload === "string" ? { parent_page_id: payload } : (payload ?? {});
  return request<{
    installation: NotionOAuthInstallation;
    trigger_page_id: string;
    requests_data_source_id: string;
    requests_database_page_id: string;
  }>(`/api/integrations/notion/oauth/${installationId}/provision`, {
    method: "POST",
    body: JSON.stringify(body),
  });
};
export const deleteNotionOAuthInstallation = (installationId: string) =>
  request<void>(`/api/integrations/notion/oauth/${installationId}`, {
    method: "DELETE",
  });

// The following functions support Slack integrations.
export type SlackOAuthInstallationConfig = {
  enabled: boolean;
  default_project_id: string | null;
  default_branch: string;
  analysis_branch_mode: "per_request" | "default_branch";
  allowed_channel_ids: string[];
};
export type SlackOAuthInstallation = {
  id: string;
  team_id: string;
  team_name: string | null;
  enterprise_id: string | null;
  enterprise_name: string | null;
  app_id: string | null;
  bot_user_id: string;
  authed_user_id: string | null;
  scopes: string[];
  status: string;
  created_at: string | null;
  updated_at: string | null;
  org_id: string | null;
  config: SlackOAuthInstallationConfig | null;
};
export const startSlackOAuth = (redirectAfter?: string) => {
  const qs = redirectAfter
    ? `?redirect_after=${encodeURIComponent(redirectAfter)}`
    : "";
  return request<{ authorize_url: string; state: string }>(
    `/api/integrations/slack/oauth/start${qs}`,
  );
};
export const getSlackOAuthInstallations = () =>
  request<SlackOAuthInstallation[]>(
    "/api/integrations/slack/oauth/installations",
  );
export type SlackProvisionPayload = {
  default_project_id: string;
  default_branch?: string;
  analysis_branch_mode?: "per_request" | "default_branch";
  allowed_channel_ids?: string[];
};
export const provisionSlackOAuthInstallation = (
  installationId: string,
  payload: SlackProvisionPayload,
) =>
  request<{ installation: SlackOAuthInstallation }>(
    `/api/integrations/slack/oauth/${installationId}/provision`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
export const deleteSlackOAuthInstallation = (installationId: string) =>
  request<void>(`/api/integrations/slack/oauth/${installationId}`, {
    method: "DELETE",
  });
