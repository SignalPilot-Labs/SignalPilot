/** Runtime constants, query-param model, and pure resolvers for the notebooks page. */

import type { AnalysisTrail } from "~/lib/api";

export const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3300";
export const NOTEBOOK_PROXY_URL = process.env.NEXT_PUBLIC_NOTEBOOK_PROXY_URL ?? "";
export const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";
export const NOTION_THREAD_EVENT = "sp:notion-thread-resolved";
export const NOTION_THREAD_STORAGE_PREFIX = "sp:notion-thread:";
export const SPA_NAVIGATE_EVENT = "spa:navigate";
export const GATEWAY_PROJECT_STORAGE_KEY = "sp:gateway-project-id";
export const GATEWAY_BRANCH_STORAGE_KEY = "sp:gateway-branch-id";
export const KnownQueryParams = {
  project: "project",
  branch: "branch",
  filePath: "file",
  sessionId: "session_id",
} as const;

export type NotionThreadWindow = Window & {
  __signalPilotNotionThreadId?: string;
  __signalPilotNotionThreadByFile?: Record<string, string>;
};

export type AppState = "loading" | "no-session" | "booting" | "ready";

export type ChatTraceThread = {
  thread_id: string;
  session_id: string;
  title?: string;
  source?: string;
  status?: string;
  notebook_path?: string;
  created_at?: number;
  updated_at?: number;
};

export type ResolvedTrail = Pick<AnalysisTrail, "project_id" | "branch" | "thread_id" | "notebook_path">;

export type RuntimeMode = "project" | "notion-trail" | "notebook";
export type RuntimeProduct = "projects" | "notebooks";

export function resolveRuntimeMode({
  project,
  file,
  sessionId,
}: {
  project: string;
  file: string;
  sessionId: string;
}): RuntimeMode {
  if (project) return "project";
  if (isNotionTrailParams({ file, sessionId })) return "notion-trail";
  return "notebook";
}

export function isNotionTrailParams({
  file,
  sessionId,
}: {
  file?: string | null;
  sessionId?: string | null;
}): boolean {
  return Boolean(
    sessionId?.startsWith("session-notion-") ||
      sessionId?.startsWith("session-slack-") ||
      file?.startsWith("signalpilot-notion-analyses/"),
  );
}

export function isTrailSessionId(sessionId?: string): sessionId is string {
  return Boolean(
    sessionId?.startsWith("session-notion-") ||
      sessionId?.startsWith("session-slack-"),
  );
}
