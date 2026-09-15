import type { NotionOAuthInstallation, SlackOAuthInstallation } from "~/lib/api";
import type { WorkspaceProjectInfo } from "~/lib/types";

export function oauthStatus(installation: NotionOAuthInstallation): { label: string; tone: "healthy" | "warning" | "error" | "unknown" } {
  if (installation.status === "disconnected") return { label: "disconnected", tone: "error" };
  if (installation.config?.enabled && installation.config?.default_project_id && installation.config?.parent_page_id) {
    return { label: "active", tone: "healthy" };
  }
  if (installation.config?.enabled && (!installation.config?.default_project_id || !installation.config?.parent_page_id)) {
    return { label: "needs setup", tone: "warning" };
  }
  if (installation.status === "connected") return { label: "needs setup", tone: "warning" };
  return { label: installation.status || "unknown", tone: "unknown" };
}

export function slackStatus(installation: SlackOAuthInstallation): { label: string; tone: "healthy" | "warning" | "error" | "unknown" } {
  if (installation.status === "disconnected") return { label: "disconnected", tone: "error" };
  if (installation.config?.enabled && installation.config?.default_project_id) return { label: "active", tone: "healthy" };
  if (installation.status === "connected") return { label: "needs setup", tone: "warning" };
  return { label: installation.status || "unknown", tone: "unknown" };
}

export function shortenedId(id: string | null | undefined): string {
  return id ? `${id.slice(0, 12)}...` : "-";
}

export function notionPageUrl(id: string | null | undefined): string | null {
  if (!id) return null;
  return `https://www.notion.so/${id.replace(/-/g, "")}`;
}

export function projectLabel(project: WorkspaceProjectInfo): string {
  return project.display_name || project.name || project.id;
}

export function formatUpdatedAt(value: number | null): string {
  if (!value) return "-";
  return new Date(value * 1000).toLocaleString();
}
