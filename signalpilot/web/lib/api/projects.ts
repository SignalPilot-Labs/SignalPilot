// Projects, workspace projects, GitHub integration, and the dbt map.

import { request } from "./client";
import type {
  DbtMapInfo,
  DbtMapResponse,
  GitCredentials,
  GitHubInstallation,
  GitHubRepo,
  GitHubRepoImportResult,
  GitHubRepoLink,
} from "../types";

// Projects (legacy dbt projects)
export const getProjects = () =>
  request<import("../types").ProjectInfo[]>("/api/projects");
export const getProject = (name: string) =>
  request<import("../types").ProjectInfo>(`/api/projects/${name}`);
export const createProject = (p: Record<string, unknown>) =>
  request<import("../types").ProjectInfo>("/api/projects", {
    method: "POST",
    body: JSON.stringify(p),
  });
export const deleteProject = (name: string) =>
  request<void>(`/api/projects/${name}`, { method: "DELETE" });
export const scanProject = (name: string) =>
  request<{ message: string; model_count: number }>(
    `/api/projects/${name}/scan`,
    { method: "POST" },
  );
export const discoverDbtCloudProjects = (
  token: string,
  account_id: string,
  host: string,
) =>
  request<{ id: number; name: string; git_url: string | null }[]>(
    "/api/dbt-cloud/projects",
    {
      method: "POST",
      body: JSON.stringify({ token, account_id, host }),
    },
  );

// The following functions support workspace projects in S3.
export const getWorkspaceProjects = (status?: string) =>
  request<{
    projects: import("../types").WorkspaceProjectInfo[];
    total: number;
  }>(`/api/workspace-projects${status ? `?status=${status}` : ""}`);
export const getWorkspaceProject = (id: string) =>
  request<import("../types").WorkspaceProjectInfo>(
    `/api/workspace-projects/${id}`,
  );
export const createWorkspaceProject = (p: {
  name: string;
  display_name: string;
  description?: string;
  source?: "managed" | "github" | "dbt-cloud";
  connection_name?: string;
  git_remote?: string;
  tags?: string[];
}) =>
  request<import("../types").WorkspaceProjectInfo>("/api/workspace-projects", {
    method: "POST",
    body: JSON.stringify(p),
  });
export const updateWorkspaceProject = (
  id: string,
  p: Record<string, unknown>,
) =>
  request<import("../types").WorkspaceProjectInfo>(
    `/api/workspace-projects/${id}`,
    { method: "PUT", body: JSON.stringify(p) },
  );
export const deleteWorkspaceProject = (id: string) =>
  request<void>(`/api/workspace-projects/${id}`, { method: "DELETE" });

// The following functions support workspace project branches.
export const getWorkspaceBranches = (projectId: string) =>
  request<{ branches: import("../types").WorkspaceBranchInfo[] }>(
    `/api/workspace-projects/${projectId}/branches`,
  );
export const createWorkspaceBranch = (
  projectId: string,
  name: string,
  fromBranch = "main",
) =>
  request<import("../types").WorkspaceBranchInfo>(
    `/api/workspace-projects/${projectId}/branches`,
    {
      method: "POST",
      body: JSON.stringify({ name, from_branch: fromBranch }),
    },
  );
export const deleteWorkspaceBranch = (projectId: string, branch: string) =>
  request<void>(`/api/workspace-projects/${projectId}/branches/${branch}`, {
    method: "DELETE",
  });

// Workspace Project Files (branch-scoped)
export const getWorkspaceFiles = (
  projectId: string,
  branch = "main",
  prefix?: string,
) =>
  request<{
    project_id: string;
    branch: string;
    prefix: string;
    files: import("../types").WorkspaceFileInfo[];
  }>(
    `/api/workspace-projects/${projectId}/branches/${branch}/files${prefix ? `?prefix=${prefix}` : ""}`,
  );
export const getWorkspaceFile = (
  projectId: string,
  branch: string,
  path: string,
) =>
  request<string>(
    `/api/workspace-projects/${projectId}/branches/${branch}/files/${path}`,
    {},
    true,
  );
export const uploadWorkspaceFile = (
  projectId: string,
  branch: string,
  path: string,
  content: string,
) =>
  request<{ key: string; size: number }>(
    `/api/workspace-projects/${projectId}/branches/${branch}/files/${path}`,
    {
      method: "PUT",
      body: content,
      headers: { "Content-Type": "text/plain" },
    },
  );
export const deleteWorkspaceFile = (
  projectId: string,
  branch: string,
  path: string,
) =>
  request<void>(
    `/api/workspace-projects/${projectId}/branches/${branch}/files/${path}`,
    { method: "DELETE" },
  );

// The following functions support the user session.
export const getUserSession = (projectId: string) =>
  request<{
    user_id: string;
    project_id: string;
    active_branch: string;
    updated_at: number;
  }>(`/api/workspace-projects/${projectId}/user-session`);
export const switchBranch = (projectId: string, branch: string) =>
  request<{
    user_id: string;
    project_id: string;
    active_branch: string;
    updated_at: number;
  }>(`/api/workspace-projects/${projectId}/user-session`, {
    method: "PUT",
    body: JSON.stringify({ branch }),
  });


// The following functions support the GitHub App.
export const getGitHubInstallUrl = () =>
  request<{ install_url: string }>("/api/github/install-url");

export const getGitHubInstallations = () =>
  request<GitHubInstallation[]>("/api/github/installations");

export const deleteGitHubInstallation = (id: string) =>
  request<void>(`/api/github/installations/${id}`, { method: "DELETE" });

export const getGitHubRepos = (installationId: string) =>
  request<GitHubRepo[]>(`/api/github/installations/${installationId}/repos`);

export const linkGitHubRepo = (body: {
  project_id: string;
  installation_id: string;
  repo_full_name: string;
  repo_id: number;
  default_branch: string;
}) =>
  request<GitHubRepoLink>("/api/github/repo-links", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getGitHubImportStatus = (repoFullName: string) =>
  request<{ stage: string; done?: number; total?: number; error?: string }>(
    `/api/github/import/status?repo_full_name=${encodeURIComponent(repoFullName)}`,
  );

export const importGitHubRepo = (body: {
  installation_id: string;
  repo_full_name: string;
  repo_id: number;
  default_branch: string;
}) =>
  request<GitHubRepoImportResult>("/api/github/import", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const unlinkGitHubRepo = (linkId: string) =>
  request<void>(`/api/github/repo-links/${linkId}`, { method: "DELETE" });

export const getGitHubRepoLinks = (projectId?: string) =>
  request<GitHubRepoLink[]>(
    `/api/github/repo-links${projectId ? `?project_id=${projectId}` : ""}`,
  );

export const getGitCredentials = (projectId: string) =>
  request<GitCredentials>(`/api/github/credentials/${projectId}`);

export const getDbtProjectDir = (projectId: string, branch?: string) =>
  request<{ dbt_project_dir: string | null; detected: string[]; source: string }>(
    `/api/workspace-projects/${projectId}/dbt-project-dir${branch ? `?branch=${encodeURIComponent(branch)}` : ""}`,
  );

// The following functions support the centrally stored dbt map.
export const getDbtMap = (projectId: string, branch?: string, includeGraph = true) => {
  const qs = new URLSearchParams();
  if (branch) qs.set("branch", branch);
  if (!includeGraph) qs.set("include_graph", "false");
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return request<DbtMapResponse>(
    `/api/workspace-projects/${projectId}/dbt-map${suffix}`,
  );
};

export const compileDbtMap = (projectId: string, branch?: string) =>
  request<{ scheduled: boolean; map: DbtMapInfo | null }>(
    `/api/workspace-projects/${projectId}/dbt-map/compile${branch ? `?branch=${encodeURIComponent(branch)}` : ""}`,
    { method: "POST" },
  );
