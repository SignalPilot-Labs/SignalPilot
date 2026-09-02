"use client";

// Standalone data chat page container. The message tree, artifact
// previews, hooks, and rail parts live in sibling modules. This file
// re-exports the moved names so existing importers do not change.

import { Bot, Loader2, NotebookPen, PanelLeft, Share2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import {
  getSavedChatReport,
  getStandaloneChatBootstrap,
  getStandaloneChatProjectReadiness,
  getStandaloneConversation,
  listStandaloneConversations,
  setDefaultStandaloneChatProject,
  type ChatReportMention,
} from "~/lib/api";
import { useToast } from "~/components/ui/toast";
import {
  standaloneMessageKey,
  type OptimisticUserMessage,
} from "~/lib/standalone-chat-state";
import { projectSettingsHref } from "~/lib/project-settings-route";
import { ArtifactsPanel } from "~/components/chat/artifacts-panel";
import { useConversationArtifacts } from "~/components/chat/use-conversation-notebook";
import { pickDefaultNotebook } from "~/lib/chat-live-notebook";
import { hasArtifactsContent } from "~/lib/chat-artifacts";
import { ChatUiContext } from "~/components/chat/chat-ui-context";
import { ChatMessage } from "~/components/chat/chat-message";
import {
  isImprovementConversation,
  isStreamingStatus,
} from "~/components/chat/standalone-chat-helpers";
import {
  ChatBootstrapSpinner,
  ChatUnavailableScreen,
  ConversationMessagesSkeleton,
  ConversationNotFoundScreen,
  ConversationRail,
  QueryApprovalCard,
  ReadinessNotice,
  StarterQuestions,
} from "~/components/chat/chat-conversation-parts";
import { ChatComposerPanel } from "~/components/chat/chat-composer-panel";
import {
  useChatAutoScroll,
  useChatDraft,
  useMentionOptions,
  useNotebookPanelState,
  useStandaloneQueryApproval,
  useStandaloneRunStream,
  useStandaloneUiMessages,
} from "~/components/chat/use-standalone-chat-run";
import { useStandaloneChatActions } from "~/components/chat/use-standalone-chat-actions";
import { useOpenArtifact } from "~/components/chat/use-open-artifact";
import { ChatEmptyHero } from "~/components/chat/chat-empty-hero";
import {
  composerDisabledReason,
  readinessNotice,
} from "~/components/chat/standalone-chat-derivations";
import { ChatSettingsPanel } from "~/components/chat/chat-settings-panel";
import { useChatSettingsPanel } from "~/components/chat/use-chat-settings-panel";
import { ConnectorsProvider } from "~/components/connectors/connectors-context";

// Re-exports for existing importers of this module path.
export { ChatUiContext, useChatUi } from "~/components/chat/chat-ui-context";
export type { UiMessage } from "~/components/chat/chat-ui-context";
export { ChatMessage } from "~/components/chat/chat-message";
export { ArtifactPreview } from "~/components/chat/chat-artifact-preview";
export type { ArtifactPreviewData } from "~/components/chat/chat-artifact-preview";

export function StandaloneDataChat({
  conversationId,
  embedded = false,
}: {
  conversationId?: string;
  embedded?: boolean;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { toast } = useToast();
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
  const requestedProject = searchParams.get("project");
  const requestedReportId = searchParams.get("report");
  const [selectedReport, setSelectedReport] =
    useState<ChatReportMention | null>(null);
  const attachedReportReference = selectedReport
    ? {
        report_id: selectedReport.report_id,
        version_id: selectedReport.current_version_id,
      }
    : undefined;
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    null,
  );
  const [perQueryBudgetUsd, setPerQueryBudgetUsd] = useState(0.25);
  const [chatBudgetUsd, setChatBudgetUsd] = useState(1);
  const [draft, setDraft] = useChatDraft(conversationId);
  const [isConversationRailOpen, setIsConversationRailOpen] =
    useState(!embedded);
  const [pendingSubmission, setPendingSubmission] =
    useState<OptimisticUserMessage | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [loadingConversationId, setLoadingConversationId] = useState<
    string | null
  >(null);
  const selectedInitialized = useRef(false);

  useEffect(() => {
    if (!bootstrap || selectedInitialized.current) return;
    const requested = bootstrap.projects.find(
      (project) => project.id === requestedProject,
    );
    setSelectedProjectId(
      requested?.id ??
        bootstrap.selected_project_id ??
        bootstrap.projects[0]?.id ??
        null,
    );
    setPerQueryBudgetUsd(bootstrap.default_per_query_budget_usd);
    setChatBudgetUsd(bootstrap.default_chat_budget_usd);
    selectedInitialized.current = true;
  }, [bootstrap, requestedProject]);

  useEffect(() => {
    if (!requestedReportId || selectedReport?.report_id === requestedReportId)
      return;
    let active = true;
    void getSavedChatReport(requestedReportId)
      .then((report) => {
        if (!active) return;
        setSelectedProjectId(report.project_id);
        setSelectedReport({
          report_id: report.id,
          title: report.title,
          kind: report.kind,
          project_id: report.project_id,
          current_version_id: report.current_version_id,
        });
      })
      .catch(() => {
        if (active) toast("The attached report is unavailable", "error");
      });
    return () => {
      active = false;
    };
  }, [requestedReportId, selectedReport?.report_id, toast]);

  useEffect(() => {
    if (detail?.conversation.project_id) {
      setSelectedProjectId(detail.conversation.project_id);
      selectedInitialized.current = true;
    }
  }, [detail?.conversation.project_id]);

  const { data: readiness } = useSWR(
    selectedProjectId ? `standalone-chat-readiness:${selectedProjectId}` : null,
    () => getStandaloneChatProjectReadiness(selectedProjectId!),
    { revalidateOnFocus: false },
  );

  const currentRun = detail?.current_run ?? null;
  const events = detail?.run_events ?? [];

  // Artifacts panel resources. The gateway is the single source of truth;
  // events only trigger refetches. `loading` drives the first-paint loader.
  const {
    notebooks: conversationNotebooks,
    files: conversationFiles,
    executions: sqlTraceExecutions,
    loading: artifactsLoading,
  } = useConversationArtifacts(conversationId ?? null, events);
  // Panel-open and auto-open follow the DEFAULT (analysis) notebook.
  const defaultNotebook = pickDefaultNotebook(conversationNotebooks);
  const [notebookPanelOpen, setNotebookPanelOpen] = useNotebookPanelState(
    conversationId,
    defaultNotebook?.status,
    currentRun?.id,
  );
  // Inline artifact cards open the panel focused on their file.
  const { openFileRequest, openArtifact } = useOpenArtifact(() =>
    setNotebookPanelOpen(true),
  );
  // Chat settings share the right-hand slot with the artifacts panel.
  const settingsPanel = useChatSettingsPanel(
    notebookPanelOpen,
    setNotebookPanelOpen,
  );
  const conversationLoading = Boolean(
    conversationId && !detail && !detailError && detailLoading,
  );
  const { approvalEvent, onQueryDecision } = useStandaloneQueryApproval({
    currentRun,
    events,
    detail,
    mutateDetail,
    mutateHistory,
  });
  useStandaloneRunStream({
    conversationId,
    currentRunId: currentRun?.id,
    streamStatus: currentRun?.status,
    events,
    mutateDetail,
    mutateHistory,
  });

  const uiMessages = useStandaloneUiMessages({
    currentRun,
    detailMessages: detail?.messages,
    events,
    isSubmitting,
    pendingSubmission,
    setPendingSubmission,
  });

  const { viewportRef, shouldStickToBottomRef, onViewportScroll } =
    useChatAutoScroll(conversationId, uiMessages);

  const {
    submitText,
    onStop,
    onRetry,
    onApproveReportSuggestion,
    prefetchConversation,
    selectConversation,
    renameConversation,
    archiveConversation,
    shareConversation,
    revokeShare,
  } = useStandaloneChatActions({
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
    attachedReportReference,
    mutateDetail,
    mutateHistory,
    shouldStickToBottomRef,
  });

  const submitDisabled =
    isSubmitting ||
    conversationLoading ||
    !selectedProjectId ||
    (readiness?.ready === false && currentRun?.status !== "waiting_for_user") ||
    currentRun?.status === "queued" ||
    currentRun?.status === "waiting_for_query_approval";

  const runIsStreaming =
    currentRun?.status === "queued" || currentRun?.status === "running";

  const disabledReason = composerDisabledReason(
    selectedProjectId,
    readiness,
    currentRun,
  );

  const mentionOptions = useMentionOptions(selectedProjectId);

  const conversations = historyData?.conversations ?? [];
  const starters =
    readiness?.starter_questions ??
    (selectedProjectId === bootstrap?.selected_project_id
      ? bootstrap?.starter_questions
      : []) ??
    [];
  const empty = uiMessages.length === 0;
  const { message: unreadyMessage, showSetup: showSetupCta } =
    readinessNotice(bootstrap, readiness);

  if (bootstrapLoading) {
    return <ChatBootstrapSpinner />;
  }
  if (bootstrapError || !bootstrap?.enabled) {
    return <ChatUnavailableScreen />;
  }
  if (detailError) {
    return <ConversationNotFoundScreen onNewChat={() => router.push("/chats")} />;
  }

  const isEmptyNewChat = empty && !conversationId;
  const connectorsEnabled = Boolean(
    bootstrap.enterprise_features.mcp_connectors,
  );
  // Budgets apply to the next chat, so they are only editable on a new one.
  const budgetSettings =
    !conversationId && bootstrap.enterprise_features.query_approval
      ? { perQueryBudgetUsd, setPerQueryBudgetUsd, chatBudgetUsd, setChatBudgetUsd }
      : null;

  const composerNode = (
    <ChatComposerPanel
      draft={draft}
      setDraft={setDraft}
      submitText={submitText}
      submitDisabled={submitDisabled}
      disabledReason={disabledReason}
      runIsStreaming={runIsStreaming}
      currentRun={currentRun}
      onStop={onStop}
      mentionOptions={mentionOptions}
      conversationId={conversationId}
      bootstrap={bootstrap}
      selectedProjectId={selectedProjectId}
      onSelectProject={(projectId) => {
        setSelectedProjectId(projectId);
        void setDefaultStandaloneChatProject(projectId);
        router.replace(`/chats?project=${encodeURIComponent(projectId)}`);
      }}
      onOpenSettings={
        connectorsEnabled || budgetSettings ? settingsPanel.toggle : undefined
      }
      settingsOpen={settingsPanel.open}
    />
  );

  return (
    <ConnectorsProvider enabled={connectorsEnabled}>
    <ChatUiContext.Provider
      value={{
        events,
        artifacts: detail?.artifacts ?? [],
        conversationId: conversationId ?? null,
        files: conversationFiles,
        openArtifact,
        openChatSettings: settingsPanel.openPanel,
        onStop,
        onRetry,
        onApproveReportSuggestion,
      }}
    >
      <div
        className={
          embedded
            ? "h-full min-w-0 overflow-hidden"
            : `h-screen overflow-hidden p-4 ${
                notebookPanelOpen && !settingsPanel.open
                  ? "min-w-[1360px]"
                  : settingsPanel.open
                    ? "min-w-[1180px]"
                    : "min-w-[960px]"
              }`
        }
      >
        <div className="relative flex h-full overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg)] shadow-2xl shadow-black/20">
          {!embedded && (
            <button
              type="button"
              aria-label={
                isConversationRailOpen
                  ? "Collapse chat history"
                  : "Expand chat history"
              }
              aria-expanded={isConversationRailOpen}
              onClick={() => setIsConversationRailOpen((isOpen) => !isOpen)}
              className={`absolute top-3 z-30 flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-dim)] shadow-lg shadow-black/20 transition-[left,color,background-color] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] ${
                isConversationRailOpen ? "left-[17rem]" : "left-3"
              }`}
            >
              <PanelLeft className="h-4 w-4" />
            </button>
          )}
          {!embedded && isConversationRailOpen && (
            <ConversationRail
              conversations={conversations}
              activeId={conversationId}
              historyLoading={historyLoading}
              loadingConversationId={loadingConversationId}
              onNewConversation={() => router.push("/chats")}
              onSelectConversation={(id) => void selectConversation(id)}
              onPrefetchConversation={prefetchConversation}
              onRename={(conversation) => void renameConversation(conversation)}
              onArchive={(conversation) =>
                void archiveConversation(conversation)
              }
              onShare={(conversation) => void shareConversation(conversation)}
              onRevokeShare={(conversation) => void revokeShare(conversation)}
              sharingEnabled={Boolean(
                bootstrap.enterprise_features.organization_sharing,
              )}
            />
          )}
          <main className="relative flex min-w-0 flex-1 flex-col">
            {!embedded &&
              conversationId &&
              detail &&
              bootstrap.enterprise_features.organization_sharing && (
                <button
                  type="button"
                  aria-label="Share conversation"
                  title="Create a new authenticated team link and revoke any previous link"
                  onClick={() => void shareConversation(detail.conversation)}
                  className="absolute right-4 top-4 z-20 flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-muted)] shadow-lg shadow-black/20 hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                >
                  <Share2 className="h-4 w-4" />
                </button>
              )}
            {conversationId &&
              isImprovementConversation(detail?.conversation) && (
                <div className="flex-none px-6 pt-4">
                  <div className="mx-auto flex max-w-3xl items-center gap-2 rounded-xl border border-[var(--color-warning)]/25 bg-[var(--color-warning)]/5 px-4 py-2.5 text-xs text-[var(--color-warning)]">
                    <Bot className="h-3.5 w-3.5 flex-none" />
                    Automated improvement run
                    <span className="text-[var(--color-text-dim)]">
                      · started by SignalPilot, not a teammate
                    </span>
                  </div>
                </div>
              )}
            {conversationId && unreadyMessage && (
              <div className="flex-none px-6 pt-4">
                <ReadinessNotice
                  message={unreadyMessage}
                  showSetup={showSetupCta}
                  onSetup={() =>
                    router.push(projectSettingsHref(selectedProjectId))
                  }
                />
              </div>
            )}
            {selectedReport && (
              <div className="flex-none px-6 pt-4">
                <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 rounded-xl border border-[var(--color-success)]/25 bg-[var(--color-bg-card)] px-4 py-3 text-xs text-[var(--color-text-muted)]">
                  <span>
                    @{selectedReport.title} is attached to your next message.
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedReport(null);
                      router.replace(
                        conversationId
                          ? `/chats/${conversationId}`
                          : `/chats?project=${encodeURIComponent(selectedProjectId || "")}`,
                      );
                    }}
                    className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
                  >
                    Remove
                  </button>
                </div>
              </div>
            )}
            <div
              ref={viewportRef}
              onScroll={onViewportScroll}
              className="min-h-0 flex-1 overflow-y-auto"
            >
              {conversationLoading ? (
                <ConversationMessagesSkeleton />
              ) : empty ? (
                <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-6 py-12">
                  <ChatEmptyHero
                    composer={
                      !conversationId && (
                        <div className="-mx-6 mt-6">{composerNode}</div>
                      )
                    }
                  />
                  {unreadyMessage ? (
                    <ReadinessNotice
                      message={unreadyMessage}
                      showSetup={showSetupCta}
                      onSetup={() =>
                        router.push(projectSettingsHref(selectedProjectId))
                      }
                    />
                  ) : starters.length === 4 ? (
                    <StarterQuestions
                      questions={starters}
                      onSelect={setDraft}
                    />
                  ) : (
                    <div className="grid grid-cols-2 gap-3">
                      {[0, 1, 2, 3].map((index) => (
                        <div
                          key={index}
                          className="h-24 animate-pulse rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]"
                        />
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div data-testid="standalone-chat-messages">
                  {uiMessages.map((message) => (
                    <ChatMessage
                      key={standaloneMessageKey(conversationId, message)}
                      message={message}
                    />
                  ))}
                </div>
              )}
              {!isEmptyNewChat && (
              <div className="sticky bottom-0 bg-gradient-to-t from-[var(--color-bg)] via-[var(--color-bg)] to-transparent pt-3">
                {approvalEvent && (
                  <QueryApprovalCard
                    event={approvalEvent}
                    onDecision={onQueryDecision}
                  />
                )}
                {composerNode}
              </div>
            )}
            </div>
            {conversationId &&
              (artifactsLoading ||
                hasArtifactsContent(
                  conversationNotebooks,
                  conversationFiles,
                  sqlTraceExecutions,
                )) &&
              !notebookPanelOpen && (
              <button
                type="button"
                aria-label="Open the artifacts panel"
                title="Open the artifacts panel"
                data-testid="live-notebook-toggle"
                onClick={() => setNotebookPanelOpen(true)}
                className="absolute right-16 top-4 z-20 flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-muted)] shadow-lg shadow-black/20 hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
              >
                {artifactsLoading ? (
                  <Loader2
                    data-testid="artifacts-toggle-loading"
                    className="h-4 w-4 animate-spin"
                  />
                ) : (
                  <NotebookPen className="h-4 w-4" />
                )}
              </button>
            )}
          </main>
          {conversationId && notebookPanelOpen && !settingsPanel.open && (
            <ArtifactsPanel
              conversationId={conversationId}
              notebooks={conversationNotebooks}
              files={conversationFiles}
              executions={sqlTraceExecutions}
              loading={artifactsLoading}
              openFileRequest={openFileRequest}
              onClose={() => setNotebookPanelOpen(false)}
            />
          )}
          {settingsPanel.open && (
            <ChatSettingsPanel
              onClose={settingsPanel.closePanel}
              connectorsEnabled={connectorsEnabled}
              budgets={budgetSettings}
            />
          )}
        </div>
      </div>
    </ChatUiContext.Provider>
    </ConnectorsProvider>
  );
}
