"use client";

import { useState } from "react";
import { Code2, LayoutTemplate } from "lucide-react";
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

  // Code view shows each cell's code above its output; app view is the
  // traditional outputs-only marimo render. Both read the same document
  // and the same live kernel stream.
  const [showCode, setShowCode] = useState(true);

  return (
    <div
      data-testid="chat-notebook-view"
      className="relative flex h-full min-h-0 w-full flex-col overflow-hidden"
    >
      <div className="absolute right-3 top-2 z-30 flex overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] shadow-sm">
        <button
          type="button"
          data-testid="chat-notebook-mode-code"
          title="Show code and outputs"
          aria-pressed={showCode}
          onClick={() => setShowCode(true)}
          className={`flex items-center gap-1 px-2 py-1 text-[10px] font-medium uppercase tracking-wider transition-colors ${
            showCode
              ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
              : "text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
          }`}
        >
          <Code2 className="h-3 w-3" />
          Code
        </button>
        <button
          type="button"
          data-testid="chat-notebook-mode-app"
          title="Show outputs only (app view)"
          aria-pressed={!showCode}
          onClick={() => setShowCode(false)}
          className={`flex items-center gap-1 px-2 py-1 text-[10px] font-medium uppercase tracking-wider transition-colors ${
            !showCode
              ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
              : "text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
          }`}
        >
          <LayoutTemplate className="h-3 w-3" />
          App
        </button>
      </div>
      <NotebookProvider value={config}>
        <NotebookBoot view="read" readShowCode={showCode} />
      </NotebookProvider>
    </div>
  );
}

export default ChatNotebookView;
