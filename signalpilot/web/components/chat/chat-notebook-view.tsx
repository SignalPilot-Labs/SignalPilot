"use client";

import { useState } from "react";
import NotebookBoot from "~/components/notebook/notebook-boot";
import {
  NotebookProvider,
  type NotebookConfig,
} from "~/components/notebook/notebook-context";
import { getGatewayAuthToken, type ConversationNotebook } from "~/lib/api";

const GATEWAY_URL =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3300";
const NOTEBOOK_PROXY_URL = process.env.NEXT_PUBLIC_NOTEBOOK_PROXY_URL ?? "";

/**
 * Inline read-only view of a conversation's analysis notebook.
 *
 * Renders the gateway's notebook resource: the saved document paints first,
 * and when the resource says the kernel is live, a kiosk websocket streams
 * updates on top. The viewer never runs cells and never provisions compute.
 */
export function ChatNotebookView({
  notebook,
}: {
  notebook: ConversationNotebook;
}) {
  // Latched once. The mount key below covers every input that requires a
  // fresh boot, so a mounted view never changes its target.
  const [config] = useState<NotebookConfig>(() => ({
    gatewayUrl: GATEWAY_URL,
    notebookProxyUrl: NOTEBOOK_PROXY_URL,
    product: "notebooks",
    sessionId: notebook.gateway_session_id ?? "",
    kernelSessionId: notebook.kernel_session_id ?? undefined,
    file: notebook.notebook_path ?? undefined,
    getToken: getGatewayAuthToken,
    kioskAttach: true,
    kioskLive: notebook.status === "live",
    loadDocument: async () =>
      notebook.document
        ? {
            source: notebook.document.source,
            session: notebook.document.session,
          }
        : null,
  }));

  return (
    <div
      data-testid="chat-notebook-view"
      className="flex h-full min-h-0 w-full flex-col overflow-hidden"
    >
      <NotebookProvider value={config}>
        <NotebookBoot view="read" />
      </NotebookProvider>
    </div>
  );
}

export default ChatNotebookView;
