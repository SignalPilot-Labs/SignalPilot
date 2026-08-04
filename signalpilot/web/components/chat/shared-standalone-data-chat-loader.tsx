"use client";

import dynamic from "next/dynamic";

const SharedStandaloneDataChat = dynamic(
  () =>
    import("~/components/chat/shared-standalone-data-chat").then(
      (module) => module.SharedStandaloneDataChat,
    ),
  { ssr: false },
);

export function SharedStandaloneDataChatLoader({ token }: { token: string }) {
  return <SharedStandaloneDataChat token={token} />;
}
