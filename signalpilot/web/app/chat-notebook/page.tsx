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

// Live notebook view for the standalone chat page. Mounted in an iframe by
// the chat's right-side panel; attaches the notebook editor to the chat
// agent's running kernel session. Keep this route a tiny shell so /chats does
// not compile the notebook runtime graph until the panel actually opens.
export default function ChatNotebookPage() {
  return <ChatNotebookEmbed />;
}
