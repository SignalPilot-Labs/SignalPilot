"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Shared rendered-markdown block for chat surfaces. Uses the same wrapper
 * class and plugins as the transcript so styling stays consistent.
 */
export function ChatMarkdown({ markdown }: { markdown: string }) {
  return (
    <div className="chat-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </div>
  );
}
