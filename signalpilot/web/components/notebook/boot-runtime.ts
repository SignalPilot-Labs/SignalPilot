import { createSignalpilotClient } from "@/embed/createSignalpilotClient";
import type { SignalpilotClient } from "@/embed/types";
import { Logger } from "@/utils/Logger";
import {
  createNotebookSession,
  pingNotebookSession,
} from "~/lib/api";
import {
  setProvisionedSessionId,
  clearProvisionedSessionId,
  type NotebookConfig,
} from "./notebook-context";

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

// ── Sessionless boot ─────────────────────────────────────────────

/** Directory-local session sidecar written by the notebook server / agent runs. */
function sessionSidecarPath(file: string): string {
  const slash = file.lastIndexOf("/");
  const dir = slash === -1 ? "" : file.slice(0, slash + 1);
  const base = file.slice(slash + 1);
  return `${dir}__sp__/session/${base}.json`;
}

const SESSION_REQUIRED_KEYS = ["version", "metadata", "cells"] as const;

function parseSessionSidecar(raw: unknown): unknown | null {
  try {
    // The gateway may serve .json files with a JSON content type, in which
    // case the request helper has already parsed them.
    const parsed: unknown = typeof raw === "string" ? JSON.parse(raw) : raw;
    if (
      parsed &&
      typeof parsed === "object" &&
      SESSION_REQUIRED_KEYS.every((k) => k in (parsed as Record<string, unknown>))
    ) {
      return parsed;
    }
  } catch {
    /* corrupt sidecar — render without outputs */
  }
  return null;
}

/**
 * Load the notebook document (and its session-outputs sidecar) straight from
 * the gateway workspace store into `staticData`, parsing client-side.
 *
 * Used by the sessionless boot as the primary document source, and by the
 * eager (warm-reattach) boot as the fallback when the sandbox document fetch
 * fails — the document must render regardless of session state.
 *
 * Direct fetch on purpose — NOT web/lib's request(): that helper json-parses
 * every body and a raw .py file is not JSON. 404 is a real answer (new
 * files, absent sidecars); anything else retries briefly (fresh-load auth
 * races).
 */
async function loadDocumentFromStore(
  config: NotebookConfig,
  bootToken: string | null,
  signal: AbortSignal,
  staticData: NotebookStaticData,
): Promise<void> {
  const project = config.project;
  if (!project || !config.file || config.file.startsWith("__new__")) {
    return;
  }
  const branch = config.branch || "main";
  const gatewayBase = (config.gatewayUrl || "").replace(/\/$/, "");
  const fetchStoreFile = async (path: string): Promise<unknown | null> => {
    const encoded = path.split("/").map(encodeURIComponent).join("/");
    const url = `${gatewayBase}/api/workspace-projects/${encodeURIComponent(project)}/files/${encoded}?branch=${encodeURIComponent(branch)}`;
    for (let attempt = 0; attempt < 4; attempt++) {
      try {
        const token = (await config.getToken()) ?? bootToken;
        const response = await fetch(url, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal,
        });
        if (response.status === 404) return null;
        if (response.ok) {
          const isJson = response.headers
            .get("Content-Type")
            ?.startsWith("application/json");
          return isJson ? await response.json() : await response.text();
        }
      } catch {
        /* network hiccup — retry below */
      }
      if (signal.aborted) return null;
      await new Promise((r) => setTimeout(r, 700 * (attempt + 1)));
    }
    return null;
  };

  // Document + outputs sidecar, fetched concurrently from the store.
  const [code, sidecar] = await Promise.all([
    fetchStoreFile(config.file),
    fetchStoreFile(sessionSidecarPath(config.file)),
  ]);
  if (signal.aborted) throw new Error("Boot cancelled");

  if (typeof code === "string" && config.file.endsWith(".py")) {
    staticData.code = code;
    try {
      const { parseNotebookPy } = await import("@/core/notebook-file/parse");
      const parsed = parseNotebookPy(code);
      if (parsed) {
        staticData.notebook = parsed.notebook;
        staticData.session = sidecar ? parseSessionSidecar(sidecar) : null;
      } else {
        staticData.rawFallback = true;
      }
    } catch (err) {
      Logger.warn("Client-side notebook parse failed — raw view:", err);
      staticData.rawFallback = true;
    }
  } else if (typeof code === "string") {
    // Non-notebook file: raw editor view, still no runtime needed.
    staticData.code = code;
    staticData.rawFallback = true;
  }
}

/**
 * Boot the editor with no runtime session at all.
 *
 * Fetches the notebook file (and its session-outputs sidecar) straight from
 * the gateway workspace store, parses it client-side, and hands the editor a
 * lazy runtime whose `provision` thunk creates the sandbox session only when
 * a kernel is first needed (Run click, restart, package install).
 */
async function bootSessionless(
  config: NotebookConfig,
  bootToken: string | null,
  onPhase: (phase: BootPhase) => void,
  navigate: (href: string) => void,
  signal: AbortSignal,
): Promise<BootResult> {
  const project = config.project!;
  const branch = config.branch || "main";
  const runtimeBase = resolveRuntimeBase(config);
  clearProvisionedSessionId();

  // Cloud: on a fresh page load the Clerk token starts org-less (the org is
  // activated a beat later) and org-less tokens 401 on every project route.
  // Wait (bounded) for an org-scoped token before touching the gateway.
  // Local API keys aren't JWTs and pass the check immediately.
  const hasOrgClaim = (token: string | null): boolean => {
    if (!token) return false;
    const parts = token.split(".");
    if (parts.length !== 3) return true; // not a JWT (local API key)
    try {
      const payload = JSON.parse(
        atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")),
      ) as { o?: unknown; org_id?: unknown };
      return Boolean(payload.o || payload.org_id);
    } catch {
      return true;
    }
  };
  if (process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud") {
    for (let i = 0; i < 40 && !hasOrgClaim(bootToken) && !signal.aborted; i++) {
      await new Promise((r) => setTimeout(r, 500));
      bootToken = await config.getToken();
    }
  }

  const staticData: NotebookStaticData = {
    filename: config.file,
    gatewayToken: bootToken ?? "",
    rawFallback: false,
  };

  await loadDocumentFromStore(config, bootToken, signal, staticData);

  // Brand-new or empty notebook: scaffold a single empty cell so the editor
  // is immediately usable (typing works; first Run provisions the kernel).
  if (
    !staticData.rawFallback &&
    !staticData.notebook &&
    (!config.file || config.file.endsWith(".py") || config.file.startsWith("__new__"))
  ) {
    staticData.notebook = {
      version: "1",
      metadata: {},
      cells: [
        { id: null, name: "_", code: "", code_hash: null, config: {} },
      ],
    };
  }

  // Keep-alive ping for the lazily provisioned session; cleaned up when the
  // boot scope unmounts (NotebookBoot aborts the controller on unmount).
  let pingInterval: ReturnType<typeof setInterval> | null = null;
  const startPing = (sessionId: string) => {
    if (pingInterval) clearInterval(pingInterval);
    pingInterval = setInterval(() => {
      pingNotebookSession(sessionId).catch((err) =>
        Logger.warn("Session ping failed:", err),
      );
    }, 60_000);
  };
  signal.addEventListener("abort", () => {
    if (pingInterval) clearInterval(pingInterval);
    pingInterval = null;
  });

  const provision = async (): Promise<string> => {
    // Flush unsaved local edits to the store first so the fresh kernel
    // hydrates exactly the code the user is looking at.
    const { runPreProvisionHooks } = await import("@/core/runtime/pre-provision");
    await runPreProvisionHooks();

    const session = await createNotebookSession({
      project_id: project,
      branch,
    });
    if (!session?.id) {
      throw new Error("Runtime session was created but returned no id");
    }
    setProvisionedSessionId(session.id);
    startPing(session.id);
    return `${runtimeBase}/notebook/${session.id}`;
  };

  const client = createSignalpilotClient({
    runtimeConfig: {
      // Placeholder until provision() swaps in the real session URL. Nothing
      // fetches it: the WS transport and kernel requests all wait on
      // whenHealthy(), which only resolves after provisioning.
      url: `${runtimeBase}/notebook/__pending__`,
      authToken: async () => (await config.getToken()) ?? "",
      lazy: true,
      provision,
    },
    writeDocumentTitle: false,
    navigate,
  });

  onPhase("ready");
  return { client, staticData };
}
