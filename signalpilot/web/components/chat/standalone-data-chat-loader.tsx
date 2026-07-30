"use client";

import dynamic from "next/dynamic";

const StandaloneDataChat = dynamic(
  () =>
    import("~/components/chat/standalone-data-chat").then(
      (module) => module.StandaloneDataChat,
    ),
  { ssr: false },
);

export function StandaloneDataChatLoader({
  conversationId,
}: {
  conversationId?: string;
}) {
  return <StandaloneDataChat conversationId={conversationId} />;
}
