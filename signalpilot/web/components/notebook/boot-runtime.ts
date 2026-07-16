import { createSignalpilotClient } from "@/embed/createSignalpilotClient";
import type { SignalpilotClient } from "@/embed/types";
import { Logger } from "@/utils/Logger";
import { isGeneratedAnalysisTrailNotebook } from "./analysis-trails";
import type { NotebookConfig } from "./notebook-context";

export type BootPhase = "health" | "notion" | "syncing" | "sessions" | "ready";

export class NotebookBootUserError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NotebookBootUserError";
  }
}

export interface NotebookStaticData {
  filename?: string;
  code?: string;
  session?: unknown;
  notebook?: unknown;
  /** Gateway auth token resolved at boot (Clerk JWT in cloud, "" in local).
   * Handed to the editor so its own gateway /api calls authenticate. */
  gatewayToken?: string;
}

export interface BootResult {
  client: SignalpilotClient;
  syncResult?: { localDir: string; fileCount: number };
  staticData: NotebookStaticData;
}

function isNotionTrailParams({
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

function notionRequestIdFromSessionId(
  sessionId: string | null | undefined,
): string | undefined {
  if (
    !sessionId?.startsWith("session-notion-") &&
    !sessionId?.startsWith("session-slack-")
  ) {
    return undefined;
  }
  return sessionId.slice("session-".length);
}

function resolveRuntimeBase(config: NotebookConfig): string {
  const base = config.notebookProxyUrl ?? config.gatewayUrl;
  if (base) return base.replace(/\/$/, "");
  return typeof window === "undefined" ? "" : window.location.origin;
}

async function rehydrateNotionTrail(
  runtimeUrl: string,
  requestId: string,
  file: string | undefined,
  sessionId: string | undefined,
  headers: Record<string, string>,
  signal: AbortSignal,
): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(
      `${runtimeUrl}/api/notion-analysis/status/${requestId}`,
      {
        headers,
        signal,
      },
    );
  } catch (err) {
    if (signal.aborted) {
      throw err;
    }
    throw new NotebookBootUserError("Trail runtime unavailable");
  }
  if (resp.status === 404) {
    const details = [file, sessionId].filter(Boolean).join(" ");
    throw new NotebookBootUserError(
      details ? `Trail record not found: ${details}` : "Trail record not found",
    );
  }
  if (!resp.ok) {
    throw new NotebookBootUserError("Trail runtime unavailable");
  }
}

/**
 * Pure async boot sequence: health → optional project sync → takeover → client creation.
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
  // Auth: the proxy verifies the caller's Clerk JWT (cloud) directly; in local
  // mode there's no token. Resolve once for the boot fetches; the long-lived
  // embed client gets the getToken thunk so it always uses a fresh token.
  const bootToken = await config.getToken();
  const urlSessionId =
    typeof window === "undefined"
      ? ""
      : new URL(window.location.href).searchParams.get("session_id") ?? "";
  const isProjectRuntime = Boolean(config.project);
  const resolvedKernelSessionId =
    config.kernelSessionId ??
    (!isProjectRuntime && isNotionTrailParams({ file: config.file, sessionId: urlSessionId })
      ? urlSessionId
      : undefined);
  const isNotionTrail =
    !isProjectRuntime &&
    isNotionTrailParams({
      file: config.file,
      sessionId: resolvedKernelSessionId ?? urlSessionId,
    });
  const notionRequestId = isNotionTrail
    ? notionRequestIdFromSessionId(resolvedKernelSessionId ?? urlSessionId)
    : undefined;

  if (resolvedKernelSessionId) {
    const { setSessionId } = await import("@/core/kernel/session");
    setSessionId(resolvedKernelSessionId as any);
  }

  const runtimeBase = resolveRuntimeBase(config);
  const runtimeUrl = `${runtimeBase}/notebook/${config.sessionId}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(bootToken ? { Authorization: `Bearer ${bootToken}` } : {}),
    ...(config.project ? { "X-Gateway-Project-Id": config.project } : {}),
    ...(config.project && config.branch ? { "X-Gateway-Branch-Id": config.branch } : {}),
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

  // ── Phase 1b: Rehydrate Notion trail kernels before WS connect ─
  if (notionRequestId) {
    onPhase("notion");
    await rehydrateNotionTrail(
      runtimeUrl,
      notionRequestId,
      config.file,
      resolvedKernelSessionId,
      headers,
      signal,
    );
  }
  if (signal.aborted) throw new Error("Boot cancelled");

  // ── Phase 2: Sync dbt project files (project product only) ────
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
  if (!isNotionTrail) {
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
  }
  if (signal.aborted) throw new Error("Boot cancelled");

  // ── Phase 4: Create client ────────────────────────────────────
  const client = createSignalpilotClient({
    runtimeConfig: {
      url: runtimeUrl,
      // Thunk: resolves a fresh Clerk JWT per request (HTTP Authorization header
      // and WS Sec-WebSocket-Protocol). Empty string in local-noauth mode.
      authToken: async () => (await config.getToken()) ?? "",
      lazy: false,
      healthVerified: true,
    },
    writeDocumentTitle: false,
    navigate,
  });

  // ── Phase 5: Fetch notebook static data (file content + session) ──
  const staticData: NotebookStaticData = { filename: config.file, gatewayToken: bootToken ?? "" };
  const isGeneratedAnalysisTrail = isGeneratedAnalysisTrailNotebook({
    project: config.project,
    branch: config.branch,
    file: config.file,
  });

  if (config.file) {
    try {
      if (isGeneratedAnalysisTrail) {
        const staticResp = await fetch(
          `${runtimeUrl}/api/notebook/static?file=${encodeURIComponent(config.file)}`,
          { headers, signal },
        );
        if (staticResp.ok) {
          const payload = (await staticResp.json()) as {
            code?: string;
            filename?: string;
            session?: unknown;
            notebook?: unknown;
          };
          staticData.code = payload.code;
          staticData.filename = payload.filename || config.file;
          staticData.session = payload.session;
          staticData.notebook = payload.notebook;
        }
      }

      if (!staticData.code) {
        const detailsResp = await fetch(`${runtimeUrl}/api/files/file_details`, {
          method: "POST",
          headers,
          body: JSON.stringify({ path: config.file }),
          signal,
        });
        if (detailsResp.ok) {
          const details = (await detailsResp.json()) as { contents?: string };
          if (details.contents) {
            staticData.code = details.contents;
          }
        }
      }
    } catch (err) {
      if (!signal.aborted) Logger.warn("File fetch failed (non-fatal):", err);
    }
  }

  onPhase("ready");
  return { client, syncResult, staticData };
}
