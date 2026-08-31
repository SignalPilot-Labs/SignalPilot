"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { ChatNotebookView } from "~/components/chat/chat-notebook-view";
import { useConversationNotebook } from "~/components/chat/use-conversation-notebook";

/**
 * Full-page pop-out of a conversation's analysis notebook.
 *
 * Fetches the gateway's notebook resource for the conversation and mounts
 * the same ChatNotebookView the chat panel renders, sized to the viewport.
 * Reached from the panel's "open in a new tab" affordance.
 *
 * Query params:
 * - conversation: chat conversation id
 */
export default function ChatNotebookEmbed() {
  const searchParams = useSearchParams();
  // Latch from the FIRST render: notebook-core boot code rewrites the URL's
  // query string, and the mounted view must not be torn down when that
  // happens.
  const [conversationId] = useState(
    () => searchParams.get("conversation") || "",
  );
  const notebook = useConversationNotebook(conversationId || null, 0);

  if (!conversationId) {
    return (
      <div
        data-testid="chat-notebook-missing-params"
        className="flex min-h-screen items-center justify-center text-sm text-[var(--color-text-muted)]"
      >
        This notebook link is incomplete.
      </div>
    );
  }

  if (!notebook) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--color-text-dim)]" />
      </div>
    );
  }

  return (
    <div
      data-testid="chat-notebook-embed"
      className="h-screen w-full overflow-hidden bg-background text-foreground"
    >
      <ChatNotebookView notebook={notebook} />
    </div>
  );
}
