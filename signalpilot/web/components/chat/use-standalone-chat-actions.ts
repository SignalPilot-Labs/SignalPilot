"use client";

// Imperative actions for the standalone data chat: submit, stop, retry,
// report approval, conversation load/select, and rail management.

import { useRouter } from "next/navigation";
import {
  useCallback,
  useRef,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from "react";
import { useSWRConfig } from "swr";
import {
  archiveStandaloneConversation,
  approveChatReportSuggestion,
  cancelStandaloneRun,
  clarifyStandaloneRun,
  createStandaloneConversation,
  createStandaloneRun,
  getStandaloneConversation,
  renameStandaloneConversation,
  retryStandaloneRun,
  revokeStandaloneConversationShare,
  shareStandaloneConversation,
  steerStandaloneRun,
  type ChatReportMention,
  type StandaloneChatRun,
  type StandaloneChatModel,
  type StandaloneConversation,
  type StandaloneConversationDetail,
} from "~/lib/api";
import { useToast } from "~/components/ui/toast";
import {
  appendOptimisticUserMessage,
  markStandaloneRunStopped,
  upsertStandaloneConversation,
  type OptimisticUserMessage,
} from "~/lib/standalone-chat-state";
import type {
  DetailMutator,
  HistoryMutator,
} from "~/components/chat/use-standalone-chat-run";

export function useStandaloneChatActions({
  conversationId,
  currentRun,
  isSubmitting,
  setIsSubmitting,
  setPendingSubmission,
  setDraft,
  setSelectedReport,
  setLoadingConversationId,
  selectedProjectId,
  perQueryBudgetUsd,
  chatBudgetUsd,
  selectedModel,
  attachedReportReference,
  mutateDetail,
  mutateHistory,
  shouldStickToBottomRef,
}: {
  conversationId?: string;
  currentRun: StandaloneChatRun | null;
  isSubmitting: boolean;
  setIsSubmitting: Dispatch<SetStateAction<boolean>>;
  setPendingSubmission: Dispatch<SetStateAction<OptimisticUserMessage | null>>;
  setDraft: Dispatch<SetStateAction<string>>;
  setSelectedReport: Dispatch<SetStateAction<ChatReportMention | null>>;
  setLoadingConversationId: Dispatch<SetStateAction<string | null>>;
  selectedProjectId: string | null;
  perQueryBudgetUsd: number;
  chatBudgetUsd: number;
  selectedModel: StandaloneChatModel;
  attachedReportReference:
    | { report_id: string; version_id: string }
    | undefined;
  mutateDetail: DetailMutator;
  mutateHistory: HistoryMutator;
  shouldStickToBottomRef: MutableRefObject<boolean>;
}) {
  const router = useRouter();
  const { cache, mutate: mutateCache } = useSWRConfig();
  const { toast } = useToast();
  const conversationPrefetches = useRef(
    new Map<string, Promise<StandaloneConversationDetail>>(),
  );

  const submitText = useCallback(
    async (text: string) => {
      text = text.trim();
      if (!text || isSubmitting) return;
      shouldStickToBottomRef.current = true;
      const optimistic: OptimisticUserMessage = {
        id: `optimistic-${crypto.randomUUID()}`,
        content: text,
        createdAt: Date.now() / 1_000,
      };
      setPendingSubmission(optimistic);
      setIsSubmitting(true);
      try {
        if (!conversationId) {
          if (!selectedProjectId) throw new Error("Select a project first");
          const created = await createStandaloneConversation(
            selectedProjectId,
            text,
            perQueryBudgetUsd,
            chatBudgetUsd,
            selectedModel,
            attachedReportReference,
          );
          setSelectedReport(null);
          await mutateCache(
            `standalone-chat-conversation:${created.conversation.id}`,
            created,
            { revalidate: false },
          );
          await mutateHistory(
            (current) => ({
              conversations: upsertStandaloneConversation(
                current?.conversations ?? [],
                created.conversation,
              ),
            }),
            { revalidate: false },
          );
          router.replace(`/chats/${created.conversation.id}`);
          void mutateHistory();
          return;
        }
        await mutateDetail(
          (current) =>
            current
              ? appendOptimisticUserMessage(current, optimistic)
              : current,
          { revalidate: false },
        );
        if (currentRun?.status === "running") {
          const queuedMessage = await steerStandaloneRun(currentRun.id, text);
          await mutateDetail(
            (current) =>
              current
                ? {
                    ...current,
                    messages: current.messages.map((message) =>
                      message.id === optimistic.id ? queuedMessage : message,
                    ),
                  }
                : current,
            { revalidate: false },
          );
          setPendingSubmission(null);
          void mutateDetail();
          void mutateHistory();
          return;
        }
        let run;
        if (currentRun?.status === "waiting_for_user") {
          run = await clarifyStandaloneRun(currentRun.id, text);
        } else {
          run = await createStandaloneRun(
            conversationId,
            text,
            attachedReportReference,
          );
          if (attachedReportReference)
            router.replace(`/chats/${conversationId}`);
          setSelectedReport(null);
        }
        await mutateDetail(
          (current) =>
            current
              ? {
                  ...current,
                  conversation: {
                    ...current.conversation,
                    run_status: run.status,
                    updated_at: Date.now() / 1_000,
                  },
                  messages: current.messages.map((message) =>
                    message.id === optimistic.id
                      ? {
                          ...message,
                          metadata: {
                            ...message.metadata,
                            run_id: run.id,
                          },
                        }
                      : message,
                  ),
                  current_run: run,
                }
              : current,
          { revalidate: false },
        );
        await mutateHistory(
          (current) =>
            current
              ? {
                  conversations: current.conversations.map((conversation) =>
                    conversation.id === conversationId
                      ? {
                          ...conversation,
                          run_status: run.status,
                          updated_at: Date.now() / 1_000,
                        }
                      : conversation,
                  ),
                }
              : current,
          { revalidate: false },
        );
        setPendingSubmission(null);
        void mutateDetail();
        void mutateHistory();
      } catch (error) {
        if (conversationId) {
          await mutateDetail(
            (current) =>
              current
                ? {
                    ...current,
                    messages: current.messages.filter(
                      (message) => message.id !== optimistic.id,
                    ),
                  }
                : current,
            { revalidate: false },
          );
        }
        setPendingSubmission(null);
        setDraft(text);
        toast(
          error instanceof Error ? error.message : "Could not send message",
          "error",
        );
      } finally {
        setIsSubmitting(false);
      }
    },
    [
      conversationId,
      currentRun,
      isSubmitting,
      mutateDetail,
      mutateCache,
      mutateHistory,
      router,
      selectedProjectId,
      perQueryBudgetUsd,
      chatBudgetUsd,
      selectedModel,
      attachedReportReference,
      toast,
      setDraft,
      setIsSubmitting,
      setPendingSubmission,
      setSelectedReport,
      shouldStickToBottomRef,
    ],
  );

  const onStop = useCallback(
    async (runId: string) => {
      const stoppedAt = new Date().toISOString();
      await mutateDetail(
        (current) =>
          current
            ? markStandaloneRunStopped(current, runId, stoppedAt)
            : current,
        { revalidate: false },
      );
      await mutateHistory(
        (current) =>
          current
            ? {
                conversations: current.conversations.map((conversation) =>
                  conversation.id === conversationId
                    ? {
                        ...conversation,
                        run_status: "cancelled" as const,
                        updated_at: Date.parse(stoppedAt) / 1_000,
                      }
                    : conversation,
                ),
              }
            : current,
        { revalidate: false },
      );
      try {
        await cancelStandaloneRun(runId);
        void mutateDetail();
        void mutateHistory();
      } catch (error) {
        void mutateDetail();
        void mutateHistory();
        toast(
          error instanceof Error ? error.message : "Could not stop the run",
          "error",
        );
      }
    },
    [conversationId, mutateDetail, mutateHistory, toast],
  );
  const onRetry = useCallback(
    async (runId: string) => {
      try {
        const run = await retryStandaloneRun(runId);
        await mutateDetail(
          (current) =>
            current
              ? {
                  ...current,
                  current_run: run,
                }
              : current,
          { revalidate: false },
        );
        void mutateDetail();
        await mutateHistory();
      } catch (error) {
        toast(
          error instanceof Error ? error.message : "Could not retry the run",
          "error",
        );
      }
    },
    [mutateDetail, mutateHistory, toast],
  );
  const onApproveReportSuggestion = useCallback(
    async (messageId: string) => {
      const result = await approveChatReportSuggestion(messageId);
      await mutateDetail();
      await mutateCache(
        (key) =>
          typeof key === "string" &&
          (key.startsWith("chat-report-library:") ||
            key.startsWith("saved-chat-report:")),
      );
      return { report_id: result.report_id };
    },
    [mutateCache, mutateDetail],
  );

  const loadConversation = useCallback(
    (id: string): Promise<StandaloneConversationDetail> => {
      const key = `standalone-chat-conversation:${id}`;
      const cached = cache.get(key) as
        { data?: StandaloneConversationDetail } | undefined;
      if (cached?.data) return Promise.resolve(cached.data);
      const existing = conversationPrefetches.current.get(id);
      if (existing) return existing;
      const request = getStandaloneConversation(id)
        .then(async (conversation) => {
          await mutateCache(key, conversation, { revalidate: false });
          return conversation;
        })
        .finally(() => conversationPrefetches.current.delete(id));
      conversationPrefetches.current.set(id, request);
      return request;
    },
    [cache, mutateCache],
  );
  const prefetchConversation = useCallback(
    (id: string) => {
      router.prefetch(`/chats/${id}`);
      void loadConversation(id).catch(() => undefined);
    },
    [loadConversation, router],
  );
  const selectConversation = useCallback(
    async (id: string) => {
      if (id === conversationId) return;
      shouldStickToBottomRef.current = true;
      setLoadingConversationId(id);
      router.prefetch(`/chats/${id}`);
      try {
        await loadConversation(id);
        router.push(`/chats/${id}`);
      } catch (error) {
        toast(
          error instanceof Error
            ? error.message
            : "Could not load the conversation",
          "error",
        );
      } finally {
        setLoadingConversationId(null);
      }
    },
    [
      conversationId,
      loadConversation,
      router,
      toast,
      setLoadingConversationId,
      shouldStickToBottomRef,
    ],
  );

  const renameConversation = async (conversation: StandaloneConversation) => {
    const title = window
      .prompt("Rename conversation", conversation.title)
      ?.trim();
    if (!title || title === conversation.title) return;
    try {
      await renameStandaloneConversation(conversation.id, title);
      await mutateHistory();
      if (conversation.id === conversationId) await mutateDetail();
    } catch (error) {
      toast(
        error instanceof Error ? error.message : "Could not rename the chat",
        "error",
      );
    }
  };
  const archiveConversation = async (conversation: StandaloneConversation) => {
    if (
      !window.confirm(
        "Remove this conversation from history? This cannot be undone.",
      )
    ) {
      return;
    }
    try {
      await archiveStandaloneConversation(conversation.id);
      await mutateHistory();
      if (conversation.id === conversationId) router.push("/chats");
    } catch (error) {
      toast(
        error instanceof Error ? error.message : "Could not remove the chat",
        "error",
      );
    }
  };
  const shareConversation = async (conversation: StandaloneConversation) => {
    try {
      const grant = await shareStandaloneConversation(conversation.id);
      const url = `${window.location.origin}/chats/shared/${grant.token}`;
      try {
        await navigator.clipboard.writeText(url);
        toast("Team link copied", "success");
      } catch {
        window.prompt("Copy team link", url);
      }
    } catch (error) {
      toast(
        error instanceof Error ? error.message : "Could not share the chat",
        "error",
      );
    }
  };
  const revokeShare = async (conversation: StandaloneConversation) => {
    if (!window.confirm("Revoke all active team links for this chat?")) return;
    try {
      await revokeStandaloneConversationShare(conversation.id);
      toast("Team link revoked", "success");
    } catch (error) {
      toast(
        error instanceof Error ? error.message : "Could not revoke the link",
        "error",
      );
    }
  };

  return {
    submitText,
    onStop,
    onRetry,
    onApproveReportSuggestion,
    loadConversation,
    prefetchConversation,
    selectConversation,
    renameConversation,
    archiveConversation,
    shareConversation,
    revokeShare,
  };
}
