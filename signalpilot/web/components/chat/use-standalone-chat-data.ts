"use client";

import useSWR from "swr";
import {
  getStandaloneChatBootstrap,
  getStandaloneConversation,
  listStandaloneConversations,
} from "~/lib/api";
import { isStreamingStatus } from "~/components/chat/standalone-chat-helpers";

/** Bootstrap, conversation history, and active-conversation SWR state for the chat. */
export function useStandaloneChatData(conversationId: string | undefined) {
  const {
    data: bootstrap,
    error: bootstrapError,
    isLoading: bootstrapLoading,
  } = useSWR("standalone-chat-bootstrap", getStandaloneChatBootstrap, {
    revalidateOnFocus: false,
  });
  const {
    data: historyData,
    isLoading: historyLoading,
    mutate: mutateHistory,
  } = useSWR("standalone-chat-conversations", listStandaloneConversations, {
    // Poll fast only while a run streams (the rail shows its status change).
    // An idle page refreshes slowly; submit/stop paths mutate on demand.
    refreshInterval: (latest) =>
      latest?.conversations.some((conversation) =>
        isStreamingStatus(conversation.run_status ?? undefined),
      )
        ? 4_000
        : 30_000,
  });
  const {
    data: detail,
    error: detailError,
    isLoading: detailLoading,
    mutate: mutateDetail,
  } = useSWR(
    conversationId ? `standalone-chat-conversation:${conversationId}` : null,
    () => getStandaloneConversation(conversationId!),
    {
      refreshInterval: (latestDetail) =>
        isStreamingStatus(latestDetail?.current_run?.status) ? 1_000 : 0,
    },
  );
  return {
    bootstrap,
    bootstrapError,
    bootstrapLoading,
    historyData,
    historyLoading,
    mutateHistory,
    detail,
    detailError,
    detailLoading,
    mutateDetail,
  };
}
