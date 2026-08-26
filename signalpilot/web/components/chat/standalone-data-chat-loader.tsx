"use client";

import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";

function StandaloneDataChatLoading() {
  return (
    <div className="h-screen min-w-[960px] overflow-hidden p-4">
      <div
        role="status"
        aria-label="Loading data chat"
        className="flex h-full overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg)]"
      >
        <aside className="w-72 flex-none space-y-3 border-r border-[var(--color-border)] bg-[var(--color-sidebar)] p-4">
          <div className="h-10 animate-pulse rounded-xl bg-[var(--color-bg-card)]" />
          {[0, 1, 2, 3].map((index) => (
            <div
              key={index}
              className="h-12 animate-pulse rounded-xl bg-[var(--color-bg-card)]"
            />
          ))}
        </aside>
        <main className="flex flex-1 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
          <span className="sr-only">Loading data chat</span>
        </main>
      </div>
    </div>
  );
}

const StandaloneDataChat = dynamic(
  () =>
    import("~/components/chat/standalone-data-chat").then(
      (module) => module.StandaloneDataChat,
    ),
  { ssr: false, loading: StandaloneDataChatLoading },
);

export function StandaloneDataChatLoader({
  conversationId,
}: {
  conversationId?: string;
}) {
  return <StandaloneDataChat conversationId={conversationId} />;
}
