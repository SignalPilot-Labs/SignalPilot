import { StandaloneDataChatLoader } from "~/components/chat/standalone-data-chat-loader";

export default async function ExistingChatPage({
  params,
}: {
  params: Promise<{ conversationId: string }>;
}) {
  const { conversationId } = await params;
  return <StandaloneDataChatLoader conversationId={conversationId} />;
}
