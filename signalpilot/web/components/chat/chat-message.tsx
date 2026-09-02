"use client";

// Message components for the standalone data chat transcript.

import {
  AlertCircle,
  ChevronRight,
  CircleStop,
  Copy,
  FileChartColumn,
  Loader2,
  Play,
  Sparkles,
  Wrench,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { ChatMarkdown } from "~/components/chat/chat-markdown";
import {
  openStandaloneNotebookArchive,
  type StandaloneChatRunStatus,
  type ChatReportSuggestion,
} from "~/lib/api";
import { RunActivityBlocks, RunTimeline } from "~/components/chat/run-timeline";
import { ConnectorSignInCards } from "~/components/chat/connector-signin-card";
import { RuntimeBootCard } from "~/components/chat/runtime-boot-card";
import { ReplayControls } from "~/components/chat/replay-controls";
import {
  deriveLiveStateFromBlocks,
  extractRunPlan,
  extractRuntimeBoot,
  foldRunBlocks,
  foldRunSteps,
  shouldShowRuntimeBoot,
} from "~/lib/chat-run-steps";
import { LivePill } from "~/components/chat/live-pill";
import { PlanTracker } from "~/components/chat/plan-tracker";
import { useChatReplay } from "~/lib/chat-replay";
import { useToast } from "~/components/ui/toast";
import {
  ChatUiContext,
  useChatUi,
  type UiMessage,
} from "~/components/chat/chat-ui-context";
import { ArtifactPreview } from "~/components/chat/chat-artifact-preview";
import {
  DashboardPreviewCard,
  messageDashboardPreview,
} from "~/components/chat/chat-dashboard-preview-card";
import { ChatArtifactCards } from "~/components/chat/chat-artifact-card";
import {
  deriveArtifactCards,
  suppressCoveredCards,
} from "~/lib/chat-artifact-cards";

function WorkTimeline({ runId }: { runId: string }) {
  const { events } = useChatUi();
  const steps = useMemo(() => foldRunSteps(events, runId), [events, runId]);
  return <RunTimeline steps={steps} />;
}

function ReportSuggestionCard({
  messageId,
  suggestion,
}: {
  messageId: string;
  suggestion: ChatReportSuggestion;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const { onApproveReportSuggestion } = useChatUi();
  const [dismissed, setDismissed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [approvedReportId, setApprovedReportId] = useState(
    suggestion.approval?.report_id ?? null,
  );
  if (dismissed) return null;
  const reportId = approvedReportId || suggestion.report_id;
  const openOnly = suggestion.action === "open";
  const label =
    suggestion.action === "create"
      ? "Create report"
      : suggestion.action === "update"
        ? "Update existing report"
        : "Open report";

  const approve = async () => {
    if (busy) return;
    if (openOnly && reportId) {
      router.push(`/reports/${reportId}`);
      return;
    }
    setBusy(true);
    try {
      const result = await onApproveReportSuggestion(messageId);
      setApprovedReportId(result.report_id);
      toast(
        suggestion.action === "create" ? "Report created" : "Report updated",
        "success",
      );
    } catch (error) {
      toast(
        error instanceof Error
          ? error.message
          : "Could not publish the report action",
        "error",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mt-4 rounded-xl border border-[var(--color-success)]/25 bg-[var(--color-bg-card)] p-4">
      <div className="flex items-start gap-3">
        <FileChartColumn className="mt-0.5 h-4 w-4 flex-none text-[var(--color-success)]" />
        <div className="min-w-0 flex-1">
          <p className="text-sm text-[var(--color-text)]">
            {suggestion.action === "create"
              ? `Save “${suggestion.title}” as a durable report?`
              : `Matched “${suggestion.title}”`}
          </p>
          <p className="mt-1 text-xs leading-5 text-[var(--color-text-muted)]">
            {suggestion.reason}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {approvedReportId ? (
              <button
                type="button"
                onClick={() => router.push(`/reports/${approvedReportId}`)}
                className="rounded-lg bg-[var(--color-text)] px-3 py-2 text-xs text-[var(--color-bg)]"
              >
                Open report
              </button>
            ) : (
              <button
                type="button"
                disabled={busy || (!reportId && openOnly)}
                onClick={() => void approve()}
                className="inline-flex items-center gap-2 rounded-lg bg-[var(--color-text)] px-3 py-2 text-xs text-[var(--color-bg)] disabled:opacity-50"
              >
                {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {label}
              </button>
            )}
            {!approvedReportId && !openOnly && (
              <button
                type="button"
                onClick={() => setDismissed(true)}
                className="rounded-lg px-3 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
              >
                Not now
              </button>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function messageReportSuggestion(
  metadata: Record<string, unknown>,
): ChatReportSuggestion | null {
  const value = metadata.report_suggestion;
  if (!value || typeof value !== "object") return null;
  const suggestion = value as Partial<ChatReportSuggestion>;
  if (
    !["create", "update", "open"].includes(suggestion.action || "") ||
    typeof suggestion.artifact_id !== "string" ||
    typeof suggestion.title !== "string" ||
    typeof suggestion.reason !== "string"
  ) {
    return null;
  }
  return suggestion as ChatReportSuggestion;
}

function AssistantMessage({
  message,
  onReplay,
  replayMode = false,
}: {
  message: UiMessage;
  onReplay?: () => void;
  replayMode?: boolean;
}) {
  const runId =
    message.runId ??
    (typeof message.metadata.run_id === "string"
      ? message.metadata.run_id
      : "");
  const runStatus =
    message.runStatus ??
    (typeof message.metadata.status === "string"
      ? (message.metadata.status as StandaloneChatRunStatus)
      : "completed");
  const [showWork, setShowWork] = useState(false);
  const { artifacts, conversationId, events, files, openArtifact, onRetry, onStop } =
    useChatUi();
  const { toast } = useToast();
  const blocks = useMemo(
    () => (runId ? foldRunBlocks(events, runId) : []),
    [events, runId],
  );
  // Present only on cold sandbox starts — warm follow-ups emit no boot events.
  const runtimeBoot = useMemo(
    () => (runId ? extractRuntimeBoot(events, runId) : null),
    [events, runId],
  );
  // The agent's published plan, shown as a first-class card in the message
  // flow — pinned to the top of the viewport while the run streams, folded
  // into the transcript afterwards.
  const runPlan = useMemo(
    () => (runId ? extractRunPlan(events, runId) : null),
    [events, runId],
  );
  const steps = useMemo(
    () =>
      blocks.flatMap((block) => (block.kind === "steps" ? block.steps : [])),
    [blocks],
  );
  const blocksHaveText = blocks.some((block) => block.kind === "text");
  const runError = steps.find((step) => step.category === "error")?.detail;
  const messageRepeatsRunError =
    runStatus === "failed" &&
    Boolean(runError) &&
    message.content.trim() === runError?.trim();
  const attachedArtifacts = useMemo(
    () =>
      artifacts.filter(
        (artifact) =>
          artifact.assistant_message_id === message.id ||
          artifact.run_id === runId,
      ),
    [artifacts, message.id, runId],
  );
  const successful = runStatus === "completed";
  const running = runStatus === "queued" || runStatus === "running";
  // What the agent is doing right now: drives the caret, the inline
  // indicator and the footer pill. Idle whenever the run is not active.
  const live = useMemo(
    () => deriveLiveStateFromBlocks(blocks, runtimeBoot, runStatus),
    [blocks, runtimeBoot, runStatus],
  );
  // Inline artifact cards: run events anchor them, the file manifest is the
  // source of truth. Derived, so rehydration on refresh is free. A file the
  // legacy published previews below already render never gets a card too —
  // one artifact must not appear twice with different verbs.
  const fileCards = useMemo(
    () =>
      runId
        ? suppressCoveredCards(
            deriveArtifactCards(events, files, runId, running),
            attachedArtifacts.map((artifact) => artifact.filename),
          )
        : [],
    [attachedArtifacts, events, files, runId, running],
  );
  const runtimeArchiveAvailable =
    message.metadata.runtime_archive_available === true;
  const reportSuggestion = successful
    ? messageReportSuggestion(message.metadata)
    : null;
  const dashboardPreview = successful
    ? messageDashboardPreview(message.metadata)
    : null;
  return (
    <article
      data-chat-message-id={message.id}
      className="group mx-auto w-full max-w-3xl px-6 py-5"
    >
      <div className="flex gap-3">
        <div className="mt-0.5 flex h-7 w-7 flex-none items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          {running ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--color-success)]" />
          ) : runStatus === "failed" ? (
            <AlertCircle className="h-3.5 w-3.5 text-[var(--color-error)]" />
          ) : (
            <Sparkles className="h-3.5 w-3.5 text-[var(--color-text-muted)]" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          {shouldShowRuntimeBoot(runtimeBoot, running) && runtimeBoot && (
            <RuntimeBootCard boot={runtimeBoot} />
          )}
          {runPlan && (
            <div className={running ? "sticky top-2 z-20 mb-3" : "mb-3"}>
              <PlanTracker plan={runPlan} running={running} />
            </div>
          )}
          {(running || blocks.length > 0) && (
            <div role="status" aria-live="polite">
              <RunActivityBlocks
                blocks={blocks}
                live={live}
                running={
                  running &&
                  runtimeBoot?.phase !== "provisioning" &&
                  runtimeBoot?.phase !== "resuming"
                }
              />
            </div>
          )}
          {runId && <ConnectorSignInCards events={events} runId={runId} />}
          {!blocksHaveText && message.content && !messageRepeatsRunError && (
            <ChatMarkdown markdown={message.content} streaming={running} />
          )}
          {fileCards.length > 0 && (
            // aria-live so a pending card resolving to ready is announced.
            <div className="mt-4" aria-live="polite">
              <ChatArtifactCards
                cards={fileCards}
                conversationId={conversationId}
                onOpen={openArtifact}
              />
            </div>
          )}
          {attachedArtifacts.length > 0 && (
            <div className="mt-5 space-y-4">
              {attachedArtifacts.map((artifact) => (
                <ArtifactPreview
                  key={artifact.id}
                  artifact={artifact}
                  canSaveAsReport={successful}
                />
              ))}
            </div>
          )}
          {reportSuggestion && (
            <ReportSuggestionCard
              messageId={message.id}
              suggestion={reportSuggestion}
            />
          )}
          {dashboardPreview && (
            <DashboardPreviewCard preview={dashboardPreview} />
          )}
          {runStatus === "cancelled" && (
            <p className="mt-3 text-xs text-[var(--color-text-dim)]">
              This run was stopped. Completed work remains available below.
            </p>
          )}
          {!replayMode && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              {successful && (
                <button
                  type="button"
                  onClick={() =>
                    void navigator.clipboard
                      .writeText(message.content)
                      .catch(() => toast("Could not copy answer", "error"))
                  }
                  className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                >
                  <Copy className="h-3 w-3" />
                  Copy
                </button>
              )}
              {onReplay && successful && (
                <button
                  type="button"
                  data-testid="chat-replay-button"
                  onClick={onReplay}
                  className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                >
                  <Play className="h-3 w-3" />
                  Replay
                </button>
              )}
              {runId && (runtimeArchiveAvailable || steps.length === 0) && (
                <button
                  type="button"
                  onClick={() => {
                    if (runtimeArchiveAvailable) {
                      void openStandaloneNotebookArchive(runId).catch(() =>
                        toast("Archived notebook is unavailable", "error"),
                      );
                    } else {
                      setShowWork((value) => !value);
                    }
                  }}
                  className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                >
                  <Wrench className="h-3 w-3" />
                  View work
                  {!runtimeArchiveAvailable && (
                    <ChevronRight
                      className={`h-3 w-3 transition-transform ${showWork ? "rotate-90" : ""}`}
                    />
                  )}
                </button>
              )}
              {running && <LivePill live={live} />}
              {running && runId && (
                <span className="relative inline-flex rounded-lg">
                  <span
                    className="chat-stop-ring absolute -inset-[3px]"
                    data-state={live.state}
                    aria-hidden
                  />
                  <button
                    type="button"
                    onClick={() => void onStop(runId)}
                    className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-error)]"
                  >
                    <CircleStop className="h-3 w-3" />
                    Stop
                  </button>
                </span>
              )}
              {runStatus === "failed" && runId && (
                <button
                  type="button"
                  onClick={() => void onRetry(runId)}
                  className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                >
                  <Play className="h-3 w-3" />
                  Retry
                </button>
              )}
            </div>
          )}
          {showWork && runId && !runtimeArchiveAvailable && (
            <div className="mt-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
              <WorkTimeline runId={runId} />
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

function UserMessage({ message }: { message: UiMessage }) {
  const steeringStatus = message.metadata.steering_status;
  return (
    <article
      data-chat-message-id={message.id}
      className="mx-auto w-full max-w-3xl px-6 py-4"
    >
      <div className="ml-auto max-w-[80%] rounded-2xl rounded-br-md bg-[#2a2a2e] px-4 py-3 text-[15.5px] leading-7 text-[var(--color-text)]">
        <div className="whitespace-pre-wrap">{message.content}</div>
        {steeringStatus === "queued" && (
          <div className="mt-2 flex items-center justify-end gap-1.5 text-[11px] text-[var(--color-text-muted)]">
            <Loader2 className="h-3 w-3 animate-spin" />
            Queued · It will be picked up on the next turn
          </div>
        )}
        {steeringStatus === "picked_up" && (
          <div className="mt-2 text-right text-[11px] text-[var(--color-success)]">
            Picked up
          </div>
        )}
        {steeringStatus === "not_delivered" && (
          <div className="mt-2 text-right text-[11px] text-[var(--color-warning)]">
            Not delivered · The run finished before pickup
          </div>
        )}
      </div>
    </article>
  );
}

function messageRunId(message: UiMessage): string {
  return (
    message.runId ??
    (typeof message.metadata.run_id === "string" ? message.metadata.run_id : "")
  );
}

/**
 * Re-renders a completed message from its recorded events on the compressed
 * replay clock: 4x speed, tool waits capped at 10s, text re-streamed.
 */
function AssistantMessageReplay({
  message,
  runId,
  onExit,
}: {
  message: UiMessage;
  runId: string;
  onExit: () => void;
}) {
  const {
    events,
    artifacts,
    conversationId,
    files,
    openArtifact,
    getFileObjectUrl,
    nowMs,
    onStop,
    onRetry,
    onApproveReportSuggestion,
  } = useChatUi();
  const replay = useChatReplay(events, artifacts, runId);
  // Runs that streamed text carry text_delta events, and the blocks rebuild
  // the message from the replayed deltas. Runs that only produced a final
  // message have no deltas — for those, reveal the persisted content at the
  // moment it actually appeared: when the run completed.
  const runStreamedText = useMemo(
    () =>
      events.some(
        (event) => event.run_id === runId && event.type === "text_delta",
      ),
    [events, runId],
  );
  const replayMessage = useMemo<UiMessage>(
    () => ({
      ...message,
      content: runStreamedText ? "" : replay.finished ? message.content : "",
      runId,
      runStatus: replay.finished
        ? (message.runStatus ?? "completed")
        : "running",
    }),
    [message, replay.finished, runId, runStreamedText],
  );
  return (
    <div data-testid="chat-replay">
      <div className="mx-auto w-full max-w-3xl px-6 pt-4">
        <ReplayControls
          elapsed={replay.elapsed}
          totalMs={replay.totalMs}
          playing={replay.playing}
          onTogglePlay={replay.togglePlay}
          onRestart={replay.restart}
          onScrub={replay.scrub}
          onExit={onExit}
        />
      </div>
      <ChatUiContext.Provider
        value={{
          events: replay.visibleEvents,
          artifacts: replay.visibleArtifacts,
          conversationId,
          files,
          openArtifact,
          getFileObjectUrl,
          nowMs,
          onStop,
          onRetry,
          onApproveReportSuggestion,
          onOpenDashboardPreview: () => undefined,
        }}
      >
        <AssistantMessage message={replayMessage} replayMode />
      </ChatUiContext.Provider>
    </div>
  );
}

function ReplayableAssistantMessage({ message }: { message: UiMessage }) {
  const { events } = useChatUi();
  const [replaying, setReplaying] = useState(false);
  const runId = messageRunId(message);
  const canReplay =
    Boolean(runId) &&
    events.some((event) => event.run_id === runId && event.type !== "status");
  if (replaying && runId) {
    return (
      <AssistantMessageReplay
        message={message}
        runId={runId}
        onExit={() => setReplaying(false)}
      />
    );
  }
  return (
    <AssistantMessage
      message={message}
      onReplay={canReplay ? () => setReplaying(true) : undefined}
    />
  );
}

export function ChatMessage({ message }: { message: UiMessage }) {
  return message.role === "user" ? (
    <UserMessage message={message} />
  ) : (
    <ReplayableAssistantMessage message={message} />
  );
}
