import { createSignalpilotClient } from "@/embed/createSignalpilotClient";
import { Logger } from "@/utils/Logger";
import { clearProvisionedSessionId, type NotebookConfig } from "./notebook-context";
import { bootKioskViewer } from "./boot-kiosk";
import { bootSessionless, loadDocumentFromStore } from "./boot-sessionless";
import {
  NotebookBootUserError,
  resolveRuntimeBase,
  type BootPhase,
  type BootResult,
  type NotebookStaticData,
} from "./boot-shared";

// Boot entry point. The kiosk and sessionless variants live in sibling
// modules (boot-kiosk.ts, boot-sessionless.ts); shared types and helpers
// live in boot-shared.ts. Re-export the public surface unchanged.
export { NotebookBootUserError };
export type { BootPhase, BootResult, NotebookStaticData };

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
  // Kiosk viewer (chat live notebook panel): DOCUMENT-FIRST, kernel-free.
  // Branch BEFORE the token await so a slow token fetch never leaves the
  // viewer in the runtime-health phase.
  if (config.kioskAttach) {
    onPhase("ready");
    return bootKioskViewer(config, await config.getToken(), onPhase, navigate, signal);
  }

  // Auth: the proxy verifies the caller's Clerk JWT (cloud) directly; in local
  // mode there's no token. Resolve once for the boot fetches; the long-lived
  // embed client gets the getToken thunk so it always uses a fresh token.
  const bootToken = await config.getToken();

  // Sessionless boot (Runtime v2): a project notebook opens with NO sandbox.
  // The document and file tree come straight from the gateway workspace
  // store; the kernel sandbox is provisioned lazily on the first Run.
  if (!config.sessionId && config.project) {
    return bootSessionless(config, bootToken, onPhase, navigate, signal);
  }
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
  // Warm project reattach targets a session that claimed to be running —
  // if it's actually healthy it answers on the first probe or two. Give it
  // a short window and fall back to a sessionless boot rather than
  // hammering a dead sandbox for 15s. Fresh (non-project) boots keep the
  // long window: their sandbox may genuinely still be coming up.
  const maxHealthAttempts = isProjectRuntime ? 6 : 30;
  for (let i = 0; i < maxHealthAttempts && !signal.aborted; i++) {
    try {
      const r = await fetch(`${runtimeUrl}/health`, { headers, signal });
      if (r.ok) {
        healthy = true;
        break;
      }
      // The gateway answers 404 (no such session) / 409 (session stopped)
      // definitively for reattach targets — retrying cannot succeed.
      if (isProjectRuntime && (r.status === 404 || r.status === 409)) {
        Logger.warn(`Reattach target is gone (HTTP ${r.status})`);
        break;
      }
    } catch (err) {
      if (signal.aborted) break;
      Logger.debug("Health check attempt failed:", err);
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  if (signal.aborted) throw new Error("Boot cancelled");
  if (!healthy) {
    if (isProjectRuntime) {
      // The session row outlived its sandbox (e.g. the sandbox hit its
      // runtime timeout). Clean it up and open sessionless — the editor
      // works without a kernel and the next Run provisions a fresh one.
      Logger.warn(
        "Warm session reattach failed — clearing stale session, booting sessionless",
      );
      const { deleteNotebookSession } = await import("~/lib/api");
      await deleteNotebookSession().catch(() => {});
      clearProvisionedSessionId();
      return bootSessionless(
        { ...config, sessionId: "" },
        bootToken,
        onPhase,
        navigate,
        signal,
      );
    }
    throw new Error("Runtime did not become healthy after 15 seconds");
  }

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

    // The sandbox couldn't serve the document (dead/blocked session): fall
    // back to the workspace store so the notebook still renders kernel-free.
    if (staticData.code == null && staticData.notebook == null && config.project) {
      await loadDocumentFromStore(config, bootToken, signal, staticData);
    }
  }

  onPhase("ready");
  return { client, staticData };
}
