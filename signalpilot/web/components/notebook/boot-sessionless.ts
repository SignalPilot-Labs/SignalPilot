import { createSignalpilotClient } from "@/embed/createSignalpilotClient";
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
import {
  resolveRuntimeBase,
  type BootPhase,
  type BootResult,
  type NotebookStaticData,
} from "./boot-shared";

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
export async function loadDocumentFromStore(
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
export async function bootSessionless(
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
