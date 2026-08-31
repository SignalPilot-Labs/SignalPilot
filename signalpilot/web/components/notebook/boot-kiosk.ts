import { createSignalpilotClient } from "@/embed/createSignalpilotClient";
import { Logger } from "@/utils/Logger";
import type { NotebookConfig } from "./notebook-context";
import {
  NotebookBootUserError,
  resolveRuntimeBase,
  type BootPhase,
  type BootResult,
  type NotebookStaticData,
} from "./boot-shared";

// ── Kiosk viewer boot (document-first, kernel-free) ──────────────

/**
 * Boot the chat notebook viewer.
 *
 * The gateway's conversation notebook resource already decided everything:
 * the document to show and whether the kernel is alive. This boot only
 * renders that decision. The document paints immediately. When
 * `config.kioskLive` is true, a kiosk websocket attaches and its session
 * replay reconciles the view with the running kernel. When it is false, no
 * websocket is ever attempted, so a dead sandbox costs nothing.
 */
export async function bootKioskViewer(
  config: NotebookConfig,
  bootToken: string | null,
  onPhase: (phase: BootPhase) => void,
  navigate: (href: string) => void,
  signal: AbortSignal,
): Promise<BootResult> {
  onPhase("ready");
  const runtimeBase = resolveRuntimeBase(config);

  const staticData: NotebookStaticData = {
    filename: config.file,
    gatewayToken: bootToken ?? "",
    rawFallback: false,
  };

  try {
    const doc = await config.loadDocument?.();
    if (doc?.source) {
      staticData.code = doc.source;
      const { parseNotebookPy } = await import("@/core/notebook-file/parse");
      const parsed = parseNotebookPy(doc.source);
      if (parsed) {
        staticData.notebook = parsed.notebook;
        staticData.session = doc.session ?? null;
      } else {
        staticData.rawFallback = true;
      }
    }
  } catch (err) {
    if (signal.aborted) throw new Error("Boot cancelled");
    Logger.debug("Kiosk document load failed (non-fatal):", err);
  }

  const live = config.kioskLive === true && Boolean(config.sessionId);
  if (!live && staticData.code == null && staticData.notebook == null) {
    throw new NotebookBootUserError(
      "This notebook has ended and no saved copy is available.",
    );
  }

  // kiosk=true rides into the websocket URL. The server attaches the
  // connection as a viewer next to the kernel's active client. For a dead
  // kernel the runtime stays lazy and is never started, so the transport
  // never dials and never retries.
  const kioskUrl = `${runtimeBase}/notebook/${config.sessionId}?kiosk=true`;
  const client = createSignalpilotClient({
    runtimeConfig: live
      ? {
          url: kioskUrl,
          authToken: async () => (await config.getToken()) ?? "",
          lazy: false,
          healthVerified: true,
        }
      : {
          url: kioskUrl,
          authToken: async () => (await config.getToken()) ?? "",
          lazy: true,
          provision: async () => kioskUrl,
        },
    writeDocumentTitle: false,
    navigate,
  });

  return { client, staticData };
}
