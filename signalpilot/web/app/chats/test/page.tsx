import { Suspense } from "react";
import { StandaloneChatTestHarness } from "~/components/chat/standalone-chat-test-harness";

export const metadata = { title: "Chat UX test harness" };

/**
 * Fixture-driven replay of a full agent run for exercising the chat UX
 * without a model, gateway, or warehouse. Deterministic states are reachable
 * via /chats/test?at=<ms>&paused=1 for visual testing.
 */
export default function ChatTestPage() {
  return (
    <div className="h-screen overflow-hidden p-4">
      <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg)] shadow-2xl shadow-black/20">
      <Suspense fallback={null}>
        <StandaloneChatTestHarness />
      </Suspense>
      </div>
    </div>
  );
}
