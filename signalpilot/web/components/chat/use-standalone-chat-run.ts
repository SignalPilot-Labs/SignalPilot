"use client";

// Run-following hooks for the standalone data chat:
// event streaming, derived UI messages, query approval, and small
// per-conversation state helpers.

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { KeyedMutator } from "swr";
import {
  decideStandaloneQueryProposal,
  streamStandaloneRunEvents,
  type StandaloneChatEvent,
  type StandaloneChatBootstrap,
  type StandaloneChatMessage,
  type StandaloneChatRun,
  type StandaloneChatRunStatus,
  type StandaloneConversation,
  type StandaloneConversationDetail,
} from "~/lib/api";
import { useToast } from "~/components/ui/toast";
import { toastRequestError } from "~/components/chat/toast-request-error";
import {
  applyStandaloneChatEvent,
  assembleStandaloneRunText,
  containsStandaloneSubmission,
  deriveStandaloneRunActivity,
  isStandaloneRunReconciled,
  type OptimisticUserMessage,
} from "~/lib/standalone-chat-state";
import type { UiMessage } from "~/components/chat/chat-ui-context";
import type { ChatEventArrival } from "~/lib/chat-telemetry";
import {
  eventText,
  isStreamingStatus,
} from "~/components/chat/standalone-chat-helpers";

export type DetailMutator = KeyedMutator<StandaloneConversationDetail>;
export type HistoryMutator = KeyedMutator<{
  conversations: StandaloneConversation[];
}>;

/** Resolve the selected project once, then keep it aligned to an opened chat. */
export function useSelectedChatProject(
  bootstrap: StandaloneChatBootstrap | undefined,
  requestedProject: string | null,
  conversationProjectId: string | undefined,
) {
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const initialized = useRef(false);
  useEffect(() => {
    if (!bootstrap || initialized.current) return;
    const requested = bootstrap.projects.find(
      (project) => project.id === requestedProject,
    );
    setSelectedProjectId(
      requested?.id ??
        bootstrap.selected_project_id ??
        bootstrap.projects[0]?.id ??
        null,
    );
    initialized.current = true;
  }, [bootstrap, requestedProject]);
  useEffect(() => {
    if (!conversationProjectId) return;
    setSelectedProjectId(conversationProjectId);
    initialized.current = true;
  }, [conversationProjectId]);
  return [selectedProjectId, setSelectedProjectId] as const;
}

/** Follow the current run's event stream and fold events into SWR caches. */
export function useStandaloneRunStream({
  conversationId,
  currentRunId,
  streamStatus,
  events,
  mutateDetail,
  mutateHistory,
}: {
  conversationId?: string;
  currentRunId: string | undefined;
  streamStatus: StandaloneChatRunStatus | undefined;
  events: StandaloneChatEvent[];
  mutateDetail: DetailMutator;
  mutateHistory: HistoryMutator;
}) {
  const [arrivalSamples, setArrivalSamples] = useState<ChatEventArrival[]>([]);
  const eventsRef = useRef(events);
  useEffect(() => {
    eventsRef.current = events;
  }, [events]);
  useEffect(() => {
    setArrivalSamples([]);
  }, [conversationId]);
  useEffect(() => {
    if (!currentRunId) {
      return;
    }
    const controller = new AbortController();
    const currentEvents = eventsRef.current.filter(
      (event) => event.run_id === currentRunId,
    );
    const after = currentEvents.reduce(
      (maximum, event) => Math.max(maximum, event.sequence),
      0,
    );
    let cursor = after;
    let retryDelay = 250;
    const followRun = async () => {
      while (!controller.signal.aborted) {
        try {
          await streamStandaloneRunEvents(
            currentRunId,
            cursor,
            controller.signal,
            (event) => {
              cursor = Math.max(cursor, event.sequence);
              setArrivalSamples((current) => [
                ...current.slice(-1_999),
                {
                  runId: event.run_id,
                  sequence: event.sequence,
                  type: event.type,
                  receivedAt: Date.now(),
                },
              ]);
              void mutateDetail(
                (current) =>
                  current ? applyStandaloneChatEvent(current, event) : current,
                { revalidate: false },
              );
              if (event.type === "status") {
                const status = event.payload.status;
                if (typeof status === "string") {
                  void mutateHistory(
                    (current) =>
                      current
                        ? {
                            conversations: current.conversations.map(
                              (conversation) =>
                                conversation.id === conversationId
                                  ? {
                                      ...conversation,
                                      run_status:
                                        status as StandaloneChatRunStatus,
                                    }
                                  : conversation,
                            ),
                          }
                        : current,
                    { revalidate: false },
                  );
                }
              }
            },
          );
        } catch (error) {
          if (controller.signal.aborted) return;
          if (error instanceof DOMException && error.name === "AbortError") {
            return;
          }
        }
        if (controller.signal.aborted) return;
        try {
          const latest = await mutateDetail();
          void mutateHistory();
          if (latest && isStandaloneRunReconciled(latest, currentRunId)) {
            return;
          }
        } catch {
          // The next bounded retry reconciles transient network failures.
        }
        await new Promise((resolve) => window.setTimeout(resolve, retryDelay));
        retryDelay = Math.min(retryDelay * 2, 5_000);
      }
    };
    void followRun();
    return () => controller.abort();
  }, [conversationId, currentRunId, streamStatus, mutateDetail, mutateHistory]);
  return arrivalSamples;
}

/** Build the rendered message list, adding optimistic and synthetic rows. */
export function useStandaloneUiMessages({
  currentRun,
  detailMessages,
  events,
  isSubmitting,
  pendingSubmission,
  setPendingSubmission,
}: {
  currentRun: StandaloneChatRun | null;
  detailMessages: StandaloneChatMessage[] | undefined;
  events: StandaloneChatEvent[];
  isSubmitting: boolean;
  pendingSubmission: OptimisticUserMessage | null;
  setPendingSubmission: (value: OptimisticUserMessage | null) => void;
}) {
  const uiMessages = useMemo<UiMessage[]>(() => {
    const messages: UiMessage[] = [...(detailMessages ?? [])];
    if (currentRun) {
      const runMessages = messages.filter(
        (message) => message.metadata.run_id === currentRun.id,
      );
      const hasTerminalMessage = runMessages.some(
        (message) =>
          message.role === "assistant" &&
          ["completed", "failed", "cancelled"].includes(
            typeof message.metadata.status === "string"
              ? message.metadata.status
              : "",
          ),
      );
      const hasWaitingMessage = runMessages.some(
        (message) =>
          message.role === "assistant" &&
          message.metadata.status === "waiting_for_user",
      );
      if (
        !hasTerminalMessage &&
        !(currentRun.status === "waiting_for_user" && hasWaitingMessage)
      ) {
        const runEvents = events.filter(
          (event) => event.run_id === currentRun.id,
        );
        const resetSequence = runEvents.reduce(
          (latest, event) =>
            event.type === "status" && event.payload?.reset_text === true
              ? Math.max(latest, event.sequence)
              : latest,
          0,
        );
        const streamed = assembleStandaloneRunText(
          runEvents,
          currentRun.id,
          resetSequence,
        );
        const clarification = [...runEvents]
          .reverse()
          .find((event) => event.type === "clarification_requested");
        const error = [...runEvents]
          .reverse()
          .find((event) => event.type === "error");
        const content =
          (clarification && eventText(clarification, "message")) ||
          streamed ||
          (error && eventText(error, "message")) ||
          (currentRun.status === "cancelled"
            ? "This run was stopped."
            : currentRun.status === "completed"
              ? "Finalizing your answer…"
              : "");
        messages.push({
          id: `run-${currentRun.id}`,
          role: "assistant",
          content,
          sequence: Number.MAX_SAFE_INTEGER,
          created_at: Date.parse(currentRun.created_at) / 1_000,
          metadata: {
            run_id: currentRun.id,
            optimistic: true,
            ...(currentRun.usage ? { token_usage: currentRun.usage } : {}),
          },
          runId: currentRun.id,
          runStatus: currentRun.status,
          activity: deriveStandaloneRunActivity(runEvents, currentRun.id),
          synthetic: true,
        });
      }
    }
    if (
      pendingSubmission &&
      !containsStandaloneSubmission(messages, pendingSubmission)
    ) {
      messages.push({
        id: pendingSubmission.id,
        role: "user",
        content: pendingSubmission.content,
        sequence: Number.MAX_SAFE_INTEGER - 1,
        created_at: pendingSubmission.createdAt,
        metadata: { optimistic: true },
      });
    }
    if (
      pendingSubmission &&
      isSubmitting &&
      !isStreamingStatus(currentRun?.status)
    ) {
      messages.push({
        id: `pending-assistant-${pendingSubmission.id}`,
        role: "assistant",
        content: "",
        sequence: Number.MAX_SAFE_INTEGER,
        created_at: pendingSubmission.createdAt,
        metadata: { optimistic: true },
        runStatus: "queued",
        activity: deriveStandaloneRunActivity([], ""),
        synthetic: true,
      });
    }
    return messages;
  }, [currentRun, detailMessages, events, isSubmitting, pendingSubmission]);

  useEffect(() => {
    if (
      pendingSubmission &&
      containsStandaloneSubmission(
        detailMessages ?? [],
        pendingSubmission,
        true,
      )
    ) {
      setPendingSubmission(null);
    }
  }, [detailMessages, pendingSubmission, setPendingSubmission]);

  return uiMessages;
}

/** Surface the pending query approval and submit the user's decision. */
export function useStandaloneQueryApproval({
  currentRun,
  events,
  detail,
  mutateDetail,
  mutateHistory,
}: {
  currentRun: StandaloneChatRun | null;
  events: StandaloneChatEvent[];
  detail: StandaloneConversationDetail | undefined;
  mutateDetail: DetailMutator;
  mutateHistory: HistoryMutator;
}) {
  const { toast } = useToast();
  const approvalEvent = useMemo(() => {
    if (currentRun?.status !== "waiting_for_query_approval") return null;
    const decisions = new Set(
      events
        .filter(
          (event) =>
            event.type === "query_approved" || event.type === "query_declined",
        )
        .map((event) => eventText(event, "proposal_id")),
    );
    return (
      [...events]
        .reverse()
        .find(
          (event) =>
            event.run_id === currentRun.id &&
            event.type === "query_approval_requested" &&
            !decisions.has(eventText(event, "proposal_id")),
        ) ?? null
    );
  }, [currentRun, events]);
  const onQueryDecision = useCallback(
    async (
      decision: "approve" | "decline",
      scope: "run_once" | "current_chat" | "user_defaults" = "run_once",
    ) => {
      if (!approvalEvent || !detail) return;
      const estimate = Number(approvalEvent.payload.estimated_cost_usd ?? 0);
      const proposalId = eventText(approvalEvent, "proposal_id");
      const budgets =
        scope === "run_once"
          ? undefined
          : {
              perQueryBudgetUsd: Math.max(
                detail.conversation.per_query_budget_usd,
                estimate,
              ),
              chatBudgetUsd: Math.max(
                detail.conversation.chat_budget_usd,
                detail.conversation.actual_spend_usd + estimate,
                estimate,
              ),
            };
      try {
        await decideStandaloneQueryProposal(
          proposalId,
          decision,
          scope,
          budgets,
        );
        await mutateDetail();
        await mutateHistory();
      } catch (error) {
        toastRequestError(toast, error, "Could not save the query decision");
      }
    },
    [approvalEvent, detail, mutateDetail, mutateHistory, toast],
  );
  return { approvalEvent, onQueryDecision };
}

/** Draft persistence: keep per-conversation (or "new") drafts across reloads. */
export function useChatDraft(conversationId?: string) {
  const [draft, setDraft] = useState("");
  const draftKey = `sp:chat-draft:${conversationId ?? "new"}`;
  useEffect(() => {
    const saved =
      typeof localStorage !== "undefined" ? localStorage.getItem(draftKey) : null;
    setDraft(saved ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey]);
  useEffect(() => {
    if (typeof localStorage === "undefined") return;
    if (draft) localStorage.setItem(draftKey, draft);
    else localStorage.removeItem(draftKey);
  }, [draft, draftKey]);
  return [draft, setDraft] as const;
}

/** Keep the transcript pinned to the bottom until the user scrolls away. */
export function useChatAutoScroll(
  conversationId: string | undefined,
  uiMessages: UiMessage[],
) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const previousConversationIdRef = useRef(conversationId);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    const switchedConversation =
      previousConversationIdRef.current !== conversationId;
    previousConversationIdRef.current = conversationId;
    if (switchedConversation) shouldStickToBottomRef.current = true;
    if (!viewport || !shouldStickToBottomRef.current) return;
    viewport.scrollTop = viewport.scrollHeight;
  }, [conversationId, uiMessages]);

  const onViewportScroll = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const distanceFromBottom =
      viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    shouldStickToBottomRef.current = distanceFromBottom < 96;
  }, []);

  return { viewportRef, shouldStickToBottomRef, onViewportScroll };
}

/**
 * Auto-open the notebook panel once per run when the notebook is live.
 * A manual close stays closed for the rest of that run.
 */
export function useNotebookPanelState(
  conversationId: string | undefined,
  notebookStatus: string | undefined,
  currentRunId: string | undefined,
) {
  const [notebookPanelOpen, setNotebookPanelOpen] = useState(false);
  const notebookPanelAutoOpenedRunRef = useRef<string | null>(null);
  useEffect(() => {
    // Auto-open once per run when the notebook is live. A manual close
    // stays closed for the rest of that run.
    if (
      notebookStatus === "live" &&
      currentRunId &&
      notebookPanelAutoOpenedRunRef.current !== currentRunId
    ) {
      notebookPanelAutoOpenedRunRef.current = currentRunId;
      setNotebookPanelOpen(true);
    }
  }, [notebookStatus, currentRunId]);
  useEffect(() => {
    setNotebookPanelOpen(false);
    notebookPanelAutoOpenedRunRef.current = null;
  }, [conversationId]);
  return [notebookPanelOpen, setNotebookPanelOpen] as const;
}
