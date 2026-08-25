/**
 * Shared helpers for the e2e suite.
 *
 * The old specs hardcoded project IDs from long-gone databases and asserted
 * UI text from a previous design ("Open IDE", a bare "running" label). These
 * helpers resolve real state at runtime so the suite tests the product, not
 * a snapshot of one developer's database.
 */
import type { APIRequestContext } from "@playwright/test";

export const GATEWAY_URL = process.env.PLAYWRIGHT_GATEWAY_URL || "http://localhost:3300";
export const WEB_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3200";

export async function getApiKey(request: APIRequestContext): Promise<string> {
  const resp = await request.get(`${WEB_URL}/api/local-key`);
  const data = (await resp.json()) as { key?: string };
  if (!data?.key) throw new Error("No local API key — is the web container running in local mode?");
  return data.key;
}

export interface WorkspaceProject {
  id: string;
  name: string;
  display_name: string;
  status: string;
  tags?: string[] | null;
}

/** First active project, preferring dbt-tagged ones (their scaffold includes
 * notebooks/intro.py, which the notebook specs open). */
export async function resolveProject(request: APIRequestContext): Promise<WorkspaceProject> {
  const apiKey = await getApiKey(request);
  const resp = await request.get(`${GATEWAY_URL}/api/workspace-projects`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  });
  if (!resp.ok()) throw new Error(`workspace-projects listing failed: ${resp.status()}`);
  const body = (await resp.json()) as { projects?: WorkspaceProject[] };
  const active = (body.projects ?? []).filter((p) => p.status === "active");
  const preferred = active.find((p) => (p.tags ?? []).includes("dbt")) ?? active[0];
  if (!preferred) {
    throw new Error(
      "No active workspace projects exist — create one (Create new project) before running the e2e suite.",
    );
  }
  return preferred;
}

export async function killAllNotebookSessions(request: APIRequestContext): Promise<void> {
  const apiKey = await getApiKey(request);
  await request
    .delete(`${GATEWAY_URL}/api/notebook-sessions`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    })
    .catch(() => {});
}
