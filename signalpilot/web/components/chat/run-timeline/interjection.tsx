"use client";

import { Loader2 } from "lucide-react";
import type { StandaloneChatMessage } from "~/lib/api";

/**
 * A follow-up the user sent while the agent was working, drawn inside the
 * run: at the point the agent read it, or at the bottom of the run while it
 * is still queued (with a note), so the work that answers it flows below it.
 */
export function InterjectionBubble({
  message,
  placed,
}: {
  message: StandaloneChatMessage;
  /** Drawn where the agent read it; a placed message needs no status note. */
  placed: boolean;
}) {
  const status = placed ? "delivered" : message.metadata.steering_status;
  return (
    <div
      data-testid="chat-interjection"
      data-chat-message-id={message.id}
      data-steering-status={typeof status === "string" ? status : undefined}
      className="chat-step-in my-3 flex justify-end"
    >
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-[#2a2a2e] px-3.5 py-2 text-[14.5px] leading-6 text-[var(--color-text)]">
        <div className="whitespace-pre-wrap">{message.content}</div>
        {status === "queued" || status === "picked_up" ? (
          <div className="mt-1 flex items-center justify-end gap-1.5 text-[11px] text-[var(--color-text-muted)]">
            <Loader2 className="h-3 w-3 animate-spin" />
            Queued · the agent reads it after its current step
          </div>
        ) : status === "not_delivered" ? (
          <div className="mt-1 text-right text-[11px] text-[var(--color-warning)]">
            Not delivered · the run finished before the agent read it
          </div>
        ) : null}
      </div>
    </div>
  );
}
