import { Logger } from "@/utils/Logger";
import { store } from "@/core/state/jotai";

/**
 * Kernel-free notebook loading for tab/file switches.
 *
 * When no kernel is connected (sessionless boot), switching to another
 * notebook file cannot rely on the WS reconnect → kernel-ready flow. This
 * loads the file straight from the gateway workspace store, parses it
 * client-side, and swaps the notebook state — same recipe as the initial
 * sessionless mount.
 */

/** Directory-local session sidecar written by the notebook server / agent runs. */
function sessionSidecarPath(file: string): string {
  const normalized = file.replace(/\\/g, "/");
  const slash = normalized.lastIndexOf("/");
  const dir = slash === -1 ? "" : normalized.slice(0, slash + 1);
  const base = normalized.slice(slash + 1);
  return `${dir}__sp__/session/${base}.json`;
}

const SESSION_REQUIRED_KEYS = ["version", "metadata", "cells"] as const;

function validSessionShape(parsed: unknown): boolean {
  return Boolean(
    parsed &&
      typeof parsed === "object" &&
      SESSION_REQUIRED_KEYS.every((k) => k in (parsed as Record<string, unknown>)),
  );
}

/**
 * Load `path` from the gateway store into the notebook atoms with no kernel.
 * Returns true when the notebook state was replaced; false when the
 * sessionless path is unavailable or the file isn't parseable as a notebook
 * (caller decides the fallback).
 */
export async function loadNotebookSessionless(path: string): Promise<boolean> {
  const { hasGatewayFilePlane, gwFileDetails } = await import(
    "@/core/network/gateway-file-api"
  );
  if (!hasGatewayFilePlane() || !path.endsWith(".py")) {
    return false;
  }

  try {
    const [details, sidecar] = await Promise.all([
      gwFileDetails({ path }),
      gwFileDetails({ path: sessionSidecarPath(path) }).catch(() => null),
    ]);
    const code = details?.contents;
    if (typeof code !== "string") {
      return false;
    }

    const { parseNotebookPy } = await import("./parse");
    const parsed = parseNotebookPy(code);
    if (!parsed) {
      return false;
    }

    let session: unknown = null;
    if (sidecar?.contents && !sidecar.isBase64) {
      try {
        const candidate: unknown = JSON.parse(sidecar.contents);
        if (validSessionShape(candidate)) {
          session = candidate;
        }
      } catch {
        /* corrupt sidecar — render without outputs */
      }
    }

    const [cellsModule, sessionModule, savingState, layoutModule] =
      await Promise.all([
        import("@/core/cells/cells"),
        import("@/core/cells/session"),
        import("@/core/saving/state"),
        import("@/core/layout/layout"),
      ]);
    const notebook = sessionModule.notebookStateFromSession(
      session as never,
      parsed.notebook as never,
    );
    if (!notebook) {
      return false;
    }
    store.set(cellsModule.notebookAtom, notebook);
    const data = notebook.cellIds.inOrderIds.map((id) => notebook.cellData[id]);
    store.set(savingState.lastSavedNotebookAtom, {
      codes: data.map((d) => d.code),
      names: data.map((d) => d.name),
      configs: data.map((d) => d.config),
      layout: store.get(layoutModule.layoutStateAtom),
    });
    return true;
  } catch (error) {
    Logger.warn("Sessionless notebook load failed:", error);
    return false;
  }
}
