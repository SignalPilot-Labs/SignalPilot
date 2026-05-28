import {
  createSignalpilotClient,
  type SignalpilotClient,
} from "@/embed";
import { Logger } from "@/utils/Logger";
import type { NotebookConfig } from "./notebook-context";

export type BootPhase = "health" | "syncing" | "sessions" | "ready";

export interface BootResult {
  client: SignalpilotClient;
  syncResult?: { localDir: string; fileCount: number };
}

/**
 * Pure async boot sequence: health → sync → takeover → client creation.
 *
 * Extracted from NotebookBoot so the component is thin and this logic
 * is testable without React.
 */
export async function bootRuntime(
  config: NotebookConfig,
  onPhase: (phase: BootPhase) => void,
  navigate: (href: string) => void,
  signal: AbortSignal,
): Promise<BootResult> {
  const runtimeUrl = `${config.gatewayUrl}/notebook/${config.sessionId}`;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${config.token}`,
    "Content-Type": "application/json",
  };

  // ── Phase 1: Wait for runtime healthy ──────────────────────────
  onPhase("health");
  let healthy = false;
  for (let i = 0; i < 30 && !signal.aborted; i++) {
    try {
      const r = await fetch(`${runtimeUrl}/health`, { headers, signal });
      if (r.ok) {
        healthy = true;
        break;
      }
    } catch (err) {
      if (signal.aborted) break;
      Logger.debug("Health check attempt failed:", err);
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  if (signal.aborted) throw new Error("Boot cancelled");
  if (!healthy) throw new Error("Runtime did not become healthy after 15 seconds");

  // ── Phase 2: Sync project files (non-fatal) ───────────────────
  let syncResult: { localDir: string; fileCount: number } | undefined;
  if (config.project) {
    onPhase("syncing");
    try {
      const resp = await fetch(`${runtimeUrl}/api/project/sync-down`, {
        method: "POST",
        headers: {
          ...headers,
          "X-Gateway-Project-Id": config.project,
          ...(config.branch ? { "X-Gateway-Branch-Id": config.branch } : {}),
        },
        signal,
      });
      if (resp.ok) {
        const data = (await resp.json()) as { local_dir?: string; file_count?: number };
        if (data.local_dir) {
          syncResult = { localDir: data.local_dir, fileCount: data.file_count ?? 0 };
        }
      }
    } catch (err) {
      if (!signal.aborted) Logger.warn("Project sync failed (non-fatal):", err);
    }
  }
  if (signal.aborted) throw new Error("Boot cancelled");

  // ── Phase 2b: Scaffold if project is empty (new project) ──────
  if (config.project && syncResult && syncResult.fileCount === 0 && syncResult.localDir) {
    onPhase("syncing");
    try {
      console.log("[boot] Empty project — scaffolding...");
      await fetch(`${runtimeUrl}/api/dbt/scaffold_project`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          parentDir: syncResult.localDir,
          projectName: ".",
        }),
        signal,
      });
      // Re-sync to pick up the scaffolded files
      const resp = await fetch(`${runtimeUrl}/api/project/sync-down`, {
        method: "POST",
        headers: {
          ...headers,
          "X-Gateway-Project-Id": config.project,
          ...(config.branch ? { "X-Gateway-Branch-Id": config.branch } : {}),
        },
        signal,
      });
      if (resp.ok) {
        const data = (await resp.json()) as { local_dir?: string; file_count?: number };
        if (data.local_dir) {
          syncResult = { localDir: data.local_dir, fileCount: data.file_count ?? 0 };
        }
      }
      console.log("[boot] Scaffold complete, files:", syncResult?.fileCount);
    } catch (err) {
      if (!signal.aborted) Logger.warn("Scaffold failed (non-fatal):", err);
    }
  }
  if (signal.aborted) throw new Error("Boot cancelled");

  // ── Phase 3: Take over stale sessions ─────────────────────────
  onPhase("sessions");
  try {
    const sessResp = await fetch(`${runtimeUrl}/api/sessions`, { headers, signal });
    if (sessResp.ok) {
      const sessions = (await sessResp.json()) as Record<string, { filename?: string | null }>;
      let existingSessionId: string | undefined;
      if (config.file) {
        for (const [sid, info] of Object.entries(sessions)) {
          if (info.filename && info.filename.endsWith(config.file)) {
            existingSessionId = sid;
            break;
          }
        }
      }
      if (existingSessionId || Object.keys(sessions).length > 0) {
        const { takeoverKernel } = await import("@/core/kernel/takeover");
        await takeoverKernel(runtimeUrl, headers).catch((err) => {
          Logger.warn("Session takeover failed (non-fatal):", err);
        });
      }
      if (existingSessionId) {
        const { setSessionId } = await import("@/core/kernel/session");
        setSessionId(existingSessionId as any);
      }
    }
  } catch (err) {
    if (!signal.aborted) Logger.warn("Session check failed:", err);
  }
  if (signal.aborted) throw new Error("Boot cancelled");

  // ── Phase 4: Create client ────────────────────────────────────
  const client = createSignalpilotClient({
    runtimeConfig: {
      url: runtimeUrl,
      authToken: config.token,
      lazy: false,
      healthVerified: true,
    },
    writeDocumentTitle: false,
    navigate,
  });

  onPhase("ready");
  return { client, syncResult };
}
