"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { ChatNotebookView } from "~/components/chat/chat-notebook-view";

/**
 * Full-page pop-out of the chat agent's live analysis notebook.
 *
 * Mounts the same inline ChatNotebookView the chat panel renders, sized to
 * the viewport. Reached from the panel's "open in a new tab" affordance.
 *
 * Query params:
 * - gw_session:  gateway notebook session id (the /notebook/{id} proxy path)
 * - session_id:  kernel session id inside the runtime (s_xxxxxx)
 * - file:        absolute path of the analysis notebook inside the sandbox
 */
export default function ChatNotebookEmbed() {
  const searchParams = useSearchParams();
  // Latch the attach params from the FIRST render: notebook-core boot code
  // rewrites the URL's query string, and the mounted view must not be torn
  // down when that happens.
  const [params] = useState(() => {
    const gwSession = searchParams.get("gw_session") || "";
    const kernelSessionId = searchParams.get("session_id") || "";
    const file = searchParams.get("file") || "";
    const runId = searchParams.get("run_id") || "";
    if (!gwSession || !kernelSessionId || !file) return null;
    return { gwSession, kernelSessionId, file, runId };
  });

  if (!params) {
    return (
      <div
        data-testid="chat-notebook-missing-params"
        className="flex min-h-screen items-center justify-center text-sm text-[var(--color-text-muted)]"
      >
        This notebook link is incomplete.
      </div>
    );
  }

  return (
    <div
      data-testid="chat-notebook-embed"
      className="h-screen w-full overflow-hidden bg-background text-foreground"
    >
      <ChatNotebookView
        gatewaySessionId={params.gwSession}
        kernelSessionId={params.kernelSessionId}
        notebookPath={params.file}
        runId={params.runId || undefined}
      />
    </div>
  );
}
