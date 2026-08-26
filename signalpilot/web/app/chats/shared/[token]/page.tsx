import { SharedStandaloneDataChatLoader } from "~/components/chat/shared-standalone-data-chat-loader";

export default async function SharedChatPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <SharedStandaloneDataChatLoader token={token} />;
}
