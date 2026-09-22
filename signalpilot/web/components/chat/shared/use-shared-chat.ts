"use client";

// Data and actions for the read-only shared chat page. The gateway's
// share-token routes are the single source of truth; nothing here derives
// state from the live run stream.

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import useSWR from "swr";
import type { ChatUiContextValue } from "~/components/chat/chat-ui-context";
import { useToast } from "~/components/ui/toast";
import {
  downloadSharedConversationFile,
  forkSharedStandaloneConversation,
  getSharedConversationFileObjectUrl,
  getSharedConversationFileText,
  getSharedConversationSqlTrace,
  getSharedStandaloneConversation,
  getStandaloneChatBootstrap,
  type SharedConversationDetail,
  type SqlTraceExecution,
} from "~/lib/api";
import { buildStandaloneUiMessages } from "~/lib/standalone-chat-ui-messages";
import { getSharedToolResult } from "~/lib/api/chat-results";

const noop = async () => undefined;
const EMPTY_EXECUTIONS: SqlTraceExecution[] = [];

/** The shared snapshot, its SQL trace, and whether the viewer may fork. */
export function useSharedChat(token: string) {
  const { data, error, isLoading } = useSWR(
    `shared-standalone-chat:${token}`,
    () => getSharedStandaloneConversation(token),
    { revalidateOnFocus: false },
  );
  // The trace only feeds the Queries tab; a failure hides that tab's rows.
  const { data: trace } = useSWR(
    data ? `shared-standalone-chat-sql-trace:${token}` : null,
    () => getSharedConversationSqlTrace(token),
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  // Same key as the live page so the bootstrap is fetched once per session.
  // A failure only hides the fork button; the transcript still renders.
  const { data: bootstrap } = useSWR(
    "standalone-chat-bootstrap",
    getStandaloneChatBootstrap,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  const uiMessages = useMemo(
    () =>
      data
        ? buildStandaloneUiMessages({
            detailMessages: data.messages,
            events: data.run_events,
          })
        : [],
    [data],
  );
  return {
    detail: data,
    error,
    isLoading,
    uiMessages,
    executions: trace?.executions ?? EMPTY_EXECUTIONS,
    forkingEnabled: Boolean(bootstrap?.enterprise_features.forking),
  };
}

/**
 * The ChatUiContext value for the shared page: every file and result read
 * goes through the share-token routes, and run controls are inert.
 */
export function useSharedChatUi(
  token: string,
  detail: SharedConversationDetail | undefined,
  openArtifact: (fileId: string) => void,
): ChatUiContextValue {
  const { toast } = useToast();
  const getFileObjectUrl = useCallback(
    (fileId: string) => getSharedConversationFileObjectUrl(token, fileId),
    [token],
  );
  const getFileText = useCallback(
    (fileId: string) => getSharedConversationFileText(token, fileId),
    [token],
  );
  const downloadFile = useCallback(
    (fileId: string, filename: string) =>
      downloadSharedConversationFile(token, fileId, filename).catch(() => {
        toast("This file is no longer available.", "error");
      }),
    [toast, token],
  );
  const getToolResultRows = useCallback(
    (resultId: string, opts?: { offset?: number; limit?: number }) =>
      getSharedToolResult(token, resultId, opts),
    [token],
  );
  const events = detail?.run_events;
  const files = detail?.files;
  return useMemo<ChatUiContextValue>(
    () => ({
      events: events ?? [],
      conversationId: null,
      files: files ?? [],
      openArtifact,
      getFileObjectUrl,
      getFileText,
      downloadFile,
      getToolResultRows,
      readOnly: true,
      onStop: noop,
      onRetry: noop,
    }),
    [
      downloadFile,
      events,
      files,
      getFileObjectUrl,
      getFileText,
      getToolResultRows,
      openArtifact,
    ],
  );
}

/** "Fork to my chats": one call, then land on the new conversation. */
export function useForkSharedChat(token: string) {
  const router = useRouter();
  const { toast } = useToast();
  const [forking, setForking] = useState(false);
  const fork = useCallback(async () => {
    setForking(true);
    try {
      const forked = await forkSharedStandaloneConversation(token);
      router.push(`/chats/${forked.id}`);
    } catch (error) {
      toast(
        error instanceof Error ? error.message : "Could not fork this chat",
        "error",
      );
      setForking(false);
    }
  }, [router, toast, token]);
  return { forking, fork };
}
