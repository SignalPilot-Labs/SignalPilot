"use client";

import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";

const ChatNotebookEmbed = dynamic(
  () => import("~/components/chat/chat-notebook-embed"),
  {
    ssr: false,
    loading: () => (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--color-text-dim)]" />
      </div>
    ),
  },
);

// Full-page pop-out of a conversation's analysis notebook. Keep this route
// a tiny shell so the notebook runtime graph compiles only when the page
// opens.
export default function ChatNotebookPage() {
  return <ChatNotebookEmbed />;
}
