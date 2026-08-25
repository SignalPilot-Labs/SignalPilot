import { createSignalpilotClient } from "@/embed/createSignalpilotClient";
import type { SignalpilotClient } from "@/embed/types";
import { Logger } from "@/utils/Logger";
import type { NotebookConfig } from "./notebook-context";

export type BootPhase = "health" | "notion" | "ready";

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
  rawFallback?: boolean;
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
 * Pure async boot sequence: health → optional project sync → client creation.
 *
 * Extracted from NotebookBoot so the component is thin and this logic
 * is testable without React. Boot never takes over an existing kernel:
 * multiple tabs and user-owned runtimes must not disconnect one another.
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

  // ── Phase 2 (Runtime v2): nothing to sync ──────────────────────
  // The workspace is pulled on demand from the S3 store; there is no boot
  // clone. Deleting the sync phase is what makes cold boots fast — the
  // runtime is ready as soon as it is healthy.

  // ── Phase 3: Create client ────────────────────────────────────
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

  // ── Phase 4: Fetch notebook static data (file content + session) ──
  const staticData: NotebookStaticData = {
    filename: config.file,
    gatewayToken: bootToken ?? "",
    rawFallback: false,
  };

  if (config.file && !config.file.startsWith("__new__")) {
    try {
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
          rawFallback?: boolean;
        };
        staticData.code = payload.code;
        staticData.filename = payload.filename || config.file;
        staticData.session = payload.session;
        staticData.notebook = payload.notebook;
        staticData.rawFallback = payload.rawFallback ?? false;
      } else {
        const detailsResp = await fetch(`${runtimeUrl}/api/files/file_details`, {
          method: "POST",
          headers,
          body: JSON.stringify({ path: config.file }),
          signal,
        });
        if (detailsResp.ok) {
          const details = (await detailsResp.json()) as { contents?: string };
          staticData.code = details.contents ?? "";
          staticData.rawFallback = true;
        }
      }
    } catch (err) {
      if (!signal.aborted) Logger.warn("File fetch failed (non-fatal):", err);
    }
  }

  onPhase("ready");
  return { client, syncResult, staticData };
}
