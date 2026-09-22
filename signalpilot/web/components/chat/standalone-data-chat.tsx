"use client";

// Standalone data chat container; UI details live in sibling modules.

import { Bot, PanelLeft } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import {
  getSavedChatReport,
  getStandaloneChatProjectReadiness,
  type ChatReportMention,
} from "~/lib/api";
import { usePermissions } from "~/lib/hooks/use-permissions";
import { useToast } from "~/components/ui/toast";
import { PlanRequired } from "~/components/billing/plan-required";
import { useSubscription } from "~/lib/subscription-context";
import { gatingError } from "~/lib/api/client";
import {
  standaloneMessageKey,
  type OptimisticUserMessage,
} from "~/lib/standalone-chat-state";
import { projectSettingsHref } from "~/lib/project-settings-route";
import { useConversationArtifacts } from "~/components/chat/use-conversation-notebook";
import { hasArtifactsContent } from "~/lib/chat-artifacts";
import { ChatUiContext } from "~/components/chat/chat-ui-context";
import { ChatPaywall } from "~/components/billing/chat-paywall";
import { ChatMessage } from "~/components/chat/chat-message";
import {
  ChatReplayView,
  useReplayMode,
} from "~/components/chat/chat-replay-view";
import { isImprovementConversation } from "~/components/chat/standalone-chat-helpers";
import {
  AttachedReportBanner,
  ChatBootstrapSpinner,
  ChatUnavailableScreen,
  ConversationMessagesSkeleton,
  ConversationNotFoundScreen,
  ConversationRail,
  QueryApprovalCard,
  ReadinessNotice,
  StarterQuestions,
  StarterQuestionsSkeleton,
} from "~/components/chat/chat-conversation-parts";
import { ChatComposerPanel } from "~/components/chat/chat-composer-panel";
import {
  useChatAutoScroll,
  useChatDraft,
  useNotebookPanelState,
  useSelectedChatProject,
  useStandaloneQueryApproval,
  useStandaloneRunStream,
  useStandaloneUiMessages,
} from "~/components/chat/use-standalone-chat-run";
import { useStandaloneChatActions } from "~/components/chat/use-standalone-chat-actions";
import { useStandaloneChatData } from "~/components/chat/use-standalone-chat-data";
import { ShareLinkDialog } from "~/components/chat/share-link-dialog";
import { ChatEmptyHero } from "~/components/chat/chat-empty-hero";
import {
  chatShellClassName,
  composerDisabledReason,
  readinessNotice,
} from "~/components/chat/standalone-chat-derivations";
import {
  ChatPanelToggles,
  ChatRightPanels,
} from "~/components/chat/standalone-chat-panels";
import { useChatRightSlot } from "~/components/chat/use-chat-right-slot";
import { useArtifactNotices } from "~/components/chat/use-artifact-notices";
import { ArtifactNotices } from "~/components/chat/artifact-notices";
import { useDockScrollCompensation } from "~/components/chat/use-dock-scroll-compensation";
import { ConnectorsProvider } from "~/components/connectors/connectors-context";
import { useChatModelSettings } from "~/components/chat/use-chat-model-settings";
import { useChatBudgetSettings } from "~/components/chat/use-chat-budget-settings";
import { useDefaultChatProject } from "~/components/chat/use-default-chat-project";
import { ChatTelemetryBoundary } from "~/components/chat/chat-telemetry-panel";

export { ChatUiContext, useChatUi } from "~/components/chat/chat-ui-context";
export type { UiMessage } from "~/components/chat/chat-ui-context";
export { ChatMessage } from "~/components/chat/chat-message";

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
  const subscription = useSubscription();
  const {
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
  } = useStandaloneChatData(conversationId);
  const requestedProject = searchParams.get("project");
  const requestedReportId = searchParams.get("report");
  const requestedPrompt = searchParams.get("prompt");
  const [selectedReport, setSelectedReport] =
    useState<ChatReportMention | null>(null);
  const attachedReportReference = selectedReport
    ? {
        report_id: selectedReport.report_id,
        version_id: selectedReport.current_version_id,
      }
    : undefined;
  const [selectedProjectId, setSelectedProjectId] = useSelectedChatProject(
    bootstrap,
    requestedProject,
    detail?.conversation.project_id,
  );
  const { perQueryBudgetUsd, chatBudgetUsd, budgetSettings } =
    useChatBudgetSettings(bootstrap, conversationId);
  const { defaultProjectId, setDefaultProject } =
    useDefaultChatProject(bootstrap);
  const { can } = usePermissions();
  const [draft, setDraft] = useChatDraft(conversationId);
  const promptInitialized = useRef(false);
  const [isConversationRailOpen, setIsConversationRailOpen] =
    useState(!embedded);
  const [pendingSubmission, setPendingSubmission] =
    useState<OptimisticUserMessage | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [loadingConversationId, setLoadingConversationId] = useState<
    string | null
  >(null);

  useEffect(() => {
    if (!requestedPrompt || promptInitialized.current) return;
    setDraft(requestedPrompt);
    promptInitialized.current = true;
  }, [requestedPrompt, setDraft]);

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
  const [notebookPanelOpen, setNotebookPanelOpen] =
    useNotebookPanelState(conversationId);
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
  const eventArrivals = useStandaloneRunStream({
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
  // Right-hand slot: artifacts or chat settings — one at a time.
  const {
    settings: settingsPanel,
    openArtifacts: openArtifactsPanel,
    openFileRequest,
    openArtifact,
    openNotebook,
  } = useChatRightSlot({
    artifactsOpen: notebookPanelOpen,
    setArtifactsOpen: setNotebookPanelOpen,
  });
  // New notebooks, charts, dashboards and reports raise a notice under the
  // panel toggle instead of opening the panel by themselves.
  const artifactNotices = useArtifactNotices({
    conversationId,
    notebooks: conversationNotebooks,
    files: conversationFiles,
    filesLoading: artifactsLoading,
    currentRunId: currentRun?.id,
    panelOpen: notebookPanelOpen || settingsPanel.open,
    openArtifact,
    openNotebook,
  });

  const { viewportRef, shouldStickToBottomRef, onViewportScroll } =
    useChatAutoScroll(conversationId, uiMessages);
  // The plan dock grows upward; keep the last transcript line above it.
  const composerDockRef = useDockScrollCompensation(viewportRef);
  const { selectedModel, selectedEffort, modelSettings } = useChatModelSettings({
    conversationId,
    conversationModel: detail?.conversation.model,
    conversationEffort: detail?.conversation.effort,
    defaultModel: bootstrap?.default_model,
    defaultEffort: bootstrap?.default_effort,
    options: bootstrap?.available_models ?? [],
    effortOptions: bootstrap?.available_efforts ?? [],
    runStatus: currentRun?.status,
    mutateDetail,
  });

  const {
    submitText,
    onStop,
    onRetry,
    prefetchConversation,
    selectConversation,
    renameConversation,
    archiveConversation,
    shareConversation,
    shareLink,
    dismissShareLink,
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
    selectedModel,
    selectedEffort,
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
  const { canReplay, replaying, enterReplay, exitReplay } = useReplayMode(
    conversationId,
    events,
    runIsStreaming,
  );

  const disabledReason = composerDisabledReason(
    selectedProjectId,
    readiness,
    currentRun,
  );

  const conversations = historyData?.conversations ?? [];
  const starters =
    readiness?.starter_questions ??
    (selectedProjectId === bootstrap?.selected_project_id
      ? bootstrap?.starter_questions
      : []) ??
    [];
  const empty = uiMessages.length === 0;
  const { message: unreadyMessage, showSetup: showSetupCta } =
    readinessNotice(bootstrap, readiness, can("projects.write"));

  if (bootstrapLoading) {
    return <ChatBootstrapSpinner />;
  }
  if (bootstrap?.plan_locked) {
    return <ChatPaywall />;
  }
  if (bootstrapError || !bootstrap?.enabled) {
    // A free org gets 200 with `enabled: false` and its entitlement; a gated
    // route answers 402 plan_required. Both are the plan prompt. Anything
    // else (a kill switch, 503 not_available_in_deployment, an outage) is not
    // something a plan change fixes.
    const planRequired =
      bootstrap?.entitlement?.is_billable === false ||
      gatingError(bootstrapError)?.error === "plan_required" ||
      (subscription.isLoaded && !subscription.isBillable);
    if (planRequired) {
      return (
        <PlanRequired
          feature="data chat"
          description="Ask questions of your governed warehouse and get receipted answers with evidence."
        />
      );
    }
    return <ChatUnavailableScreen />;
  }
  if (detailError) {
    return (
      <ConversationNotFoundScreen onNewChat={() => router.push("/chats")} />
    );
  }

  const isEmptyNewChat = empty && !conversationId;
  const connectorsEnabled = Boolean(
    bootstrap.enterprise_features.mcp_connectors,
  );
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
      conversationId={conversationId}
      bootstrap={bootstrap}
      selectedProjectId={selectedProjectId}
      onSelectProject={(projectId) => {
        // A pick is for this chat only; the org default is a separate,
        // admin-only action.
        setSelectedProjectId(projectId);
        router.replace(`/chats?project=${encodeURIComponent(projectId)}`);
      }}
      defaultProjectId={defaultProjectId}
      onSetDefaultProject={(projectId) => void setDefaultProject(projectId)}
      onOpenSettings={settingsPanel.toggle}
      settingsOpen={settingsPanel.open}
    />
  );

  return (
    <ChatTelemetryBoundary
      messages={uiMessages}
      events={events}
      currentRun={currentRun}
      arrivals={eventArrivals}
      running={runIsStreaming}
    >
    <ConnectorsProvider enabled={connectorsEnabled}>
    <ChatUiContext.Provider
      value={{
        events,
        conversationId: conversationId ?? null,
        files: conversationFiles,
        openArtifact,
        openChatSettings: settingsPanel.openPanel,
        onStop,
        onRetry,
      }}
    >
      <div
        className={chatShellClassName(
          embedded,
          settingsPanel.open,
          notebookPanelOpen,
        )}
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
              <AttachedReportBanner
                title={selectedReport.title}
                onRemove={() => {
                  setSelectedReport(null);
                  router.replace(
                    conversationId
                      ? `/chats/${conversationId}`
                      : `/chats?project=${encodeURIComponent(selectedProjectId || "")}`,
                  );
                }}
              />
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
                    <StarterQuestionsSkeleton />
                  )}
                </div>
              ) : replaying ? (
                <ChatReplayView
                  messages={uiMessages}
                  onExit={exitReplay}
                  viewportRef={viewportRef}
                />
              ) : (
                <div data-testid="standalone-chat-messages">
                  {uiMessages.map((message, index) => (
                    <ChatMessage
                      key={standaloneMessageKey(conversationId, message)}
                      message={message}
                      previousMessageAt={uiMessages[index - 1]?.created_at}
                    />
                  ))}
                </div>
              )}
              {!isEmptyNewChat && !replaying && (
                <div
                  ref={composerDockRef}
                  data-testid="chat-composer-dock"
                  className="sticky bottom-0 isolate z-30 bg-gradient-to-t from-[var(--color-bg)] via-[var(--color-bg)] to-transparent pt-3"
                >
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
            {conversationId && (
              <ChatPanelToggles
                artifactsAvailable={hasArtifactsContent(
                  conversationNotebooks,
                  conversationFiles,
                  sqlTraceExecutions,
                )}
                artifactsLoading={artifactsLoading}
                artifactsOpen={notebookPanelOpen}
                onOpenArtifacts={openArtifactsPanel}
                onShare={
                  !embedded &&
                  detail &&
                  bootstrap.enterprise_features.organization_sharing
                    ? () => void shareConversation(detail.conversation)
                    : undefined
                }
                onReplay={canReplay ? enterReplay : undefined}
              />
            )}
            {conversationId && !replaying && (
              <ArtifactNotices {...artifactNotices} />
            )}
          </main>
          {settingsPanel.open || conversationId ? (
            <ChatRightPanels
              conversationId={conversationId ?? ""}
              artifacts={{
                open: Boolean(conversationId) && notebookPanelOpen,
                notebooks: conversationNotebooks,
                files: conversationFiles,
                executions: sqlTraceExecutions,
                loading: artifactsLoading,
                openFileRequest,
                onClose: () => setNotebookPanelOpen(false),
              }}
              settings={{
                open: settingsPanel.open,
                connectorsEnabled,
                model: modelSettings,
                budgets: budgetSettings,
                onClose: settingsPanel.closePanel,
              }}
            />
          ) : null}
        </div>
      </div>
    </ChatUiContext.Provider>
    <ShareLinkDialog url={shareLink} onClose={dismissShareLink} />
    </ConnectorsProvider>
    </ChatTelemetryBoundary>
  );
}
