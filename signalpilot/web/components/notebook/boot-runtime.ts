import {
  createSignalpilotClient,
  type SignalpilotClient,
} from "@/embed";
import type { NotebookConfig } from "./notebook-context";

export type BootPhase = "loading" | "ready";

export interface NotebookStaticData {
  code: string;
  session: unknown | null; // NotebookSessionV1 | null
  notebook: unknown | null; // NotebookV1
  filename: string;
}

export interface BootResult {
  client: SignalpilotClient;
  staticData: NotebookStaticData;
}

/**
 * Single-call boot sequence: fetch static notebook data → create lazy client.
 *
 * Round 1 moved sync_down into the pod CMD (project_sync_boot.py) which runs
 * BEFORE `sp edit` binds the port. So when this fetch succeeds, the workspace
 * is already populated. No health ping, no sync POST, no /api/sessions poll.
 *
 * The WS opens only on the user's first Run press via the existing lazy-runtime
 * machinery in requests-lazy.ts (sendRun → "startConnection" → initOnce).
 */
export async function bootRuntime(
  config: NotebookConfig,
  onPhase: (phase: BootPhase) => void,
  navigate: (href: string) => void,
  signal: AbortSignal,
): Promise<BootResult> {
  onPhase("loading");

  const runtimeUrl = `${config.gatewayUrl}/notebook/${config.sessionId}`;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${config.token}`,
    "Content-Type": "application/json",
    ...(config.project ? { "X-Gateway-Project-Id": config.project } : {}),
    ...(config.branch ? { "X-Gateway-Branch-Id": config.branch } : {}),
  };

  // Single load-bearing HTTP call — fetches code + session + notebook.
  // No fallback: if this fails the error surfaces immediately to the user.
  const file = config.file ?? "";
  const url = `${runtimeUrl}/api/notebook/static?file=${encodeURIComponent(file)}`;
  const resp = await fetch(url, { headers, signal });
  if (signal.aborted) throw new Error("Boot cancelled");
  if (!resp.ok) {
    throw new Error(
      `Failed to load notebook (${resp.status}): ${await resp.text().catch(() => resp.statusText)}`,
    );
  }
  const staticData = (await resp.json()) as NotebookStaticData;

  const client = createSignalpilotClient({
    runtimeConfig: {
      url: runtimeUrl,
      authToken: config.token,
      lazy: true, // WS will not open until user's first Run press
      healthVerified: false, // first lazy startConnection runs init() which health-checks
    },
    writeDocumentTitle: false,
    navigate,
  });

  onPhase("ready");
  return { client, staticData };
}
