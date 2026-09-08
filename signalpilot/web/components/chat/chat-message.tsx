"use client";

// Message components for the standalone data chat transcript. The
// assistant turn lives in assistant-message.tsx; conversation replay in
// chat-replay-view.tsx.

import { Loader2 } from "lucide-react";
import type { UiMessage } from "~/components/chat/chat-ui-context";
import { AssistantMessage } from "~/components/chat/assistant-message";
import { MessageTiming } from "~/components/chat/chat-message-timing";

export function UserMessage({ message }: { message: UiMessage }) {
  const steeringStatus = message.metadata.steering_status;
  return (
    <article
      data-chat-message-id={message.id}
      className="mx-auto w-full max-w-3xl px-6 py-4"
    >
      <div className="ml-auto max-w-[80%] rounded-2xl rounded-br-md bg-[#2a2a2e] px-4 py-3 text-[15.5px] leading-7 text-[var(--color-text)]">
        <div className="whitespace-pre-wrap">{message.content}</div>
        {steeringStatus === "queued" && (
          <div className="mt-2 flex items-center justify-end gap-1.5 text-[11px] text-[var(--color-text-muted)]">
            <Loader2 className="h-3 w-3 animate-spin" />
            Queued · It will be picked up on the next turn
          </div>
        )}
        {steeringStatus === "picked_up" && (
          <div className="mt-2 text-right text-[11px] text-[var(--color-success)]">
            Picked up
          </div>
        )}
        {steeringStatus === "not_delivered" && (
          <div className="mt-2 text-right text-[11px] text-[var(--color-warning)]">
            Not delivered · The run finished before pickup
          </div>
        )}
      </div>
      <div className="mt-1 flex justify-end pr-1">
        <MessageTiming message={message} />
      </div>
    </article>
  );
}

export function ChatMessage({
  message,
  previousMessageAt,
}: {
  message: UiMessage;
  previousMessageAt?: number;
}) {
  return message.role === "user" ? (
    <UserMessage message={message} />
  ) : (
    <AssistantMessage message={message} previousMessageAt={previousMessageAt} />
  );
}
