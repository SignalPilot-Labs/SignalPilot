"use client";

import { useState } from "react";
import NotebookBoot from "~/components/notebook/notebook-boot";
import {
  NotebookProvider,
  type NotebookConfig,
} from "~/components/notebook/notebook-context";
import {
  getGatewayAuthToken,
  getStandaloneNotebookDocument,
} from "~/lib/api";

const GATEWAY_URL =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3300";
const NOTEBOOK_PROXY_URL = process.env.NEXT_PUBLIC_NOTEBOOK_PROXY_URL ?? "";

/**
 * Inline view of the chat agent's analysis notebook — DOCUMENT-FIRST and
 * kernel-free.
 *
 * Mounts the real notebook runtime (NotebookProvider + NotebookBoot) in read
 * mode. The document renders immediately from the best available source
 * (live sandbox document, else the run's archived source + outputs
 * snapshot); the kiosk websocket attaches in the background purely for live
 * updates while the agent works, and its absence is silent. The viewer can
 * never run or edit cells and never provisions compute.
 */
export function ChatNotebookView({
  gatewaySessionId,
  kernelSessionId,
  notebookPath,
  runId,
}: {
  /** Gateway notebook session id — the /notebook/{id} proxy path segment. */
  gatewaySessionId: string;
  /** Kernel session id inside the runtime (s_xxxxxx). */
  kernelSessionId: string;
  /** Absolute path of the analysis notebook inside the sandbox. */
  notebookPath: string;
  /** Run id — used to fetch the archived document when the sandbox is gone. */
  runId?: string;
}) {
  // Latched once: the attach target of a mounted view never changes — a new
  // notebook/kernel remounts via the key derived from these ids.
  const [config] = useState<NotebookConfig>(() => ({
    gatewayUrl: GATEWAY_URL,
    notebookProxyUrl: NOTEBOOK_PROXY_URL,
    product: "notebooks",
    sessionId: gatewaySessionId,
    kernelSessionId,
    file: notebookPath,
    getToken: getGatewayAuthToken,
    kioskAttach: true,
    loadDocument: runId
      ? async () => {
          const doc = await getStandaloneNotebookDocument(runId).catch(
            () => null,
          );
          return doc ? { source: doc.source, session: doc.session } : null;
        }
      : undefined,
  }));

  const bootKey = `${gatewaySessionId}:${kernelSessionId}:${notebookPath}`;
  return (
    <div
      data-testid="chat-notebook-view"
      className="flex h-full min-h-0 w-full flex-col overflow-hidden"
    >
      <NotebookProvider key={bootKey} value={config}>
        <NotebookBoot key={bootKey} view="read" />
      </NotebookProvider>
    </div>
  );
}

export default ChatNotebookView;
