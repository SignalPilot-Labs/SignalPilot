"use client";

// Message components for the standalone data chat transcript.

import {
  AlertCircle,
  ChevronRight,
  CircleStop,
  Copy,
  Loader2,
  Play,
  Sparkles,
  Wrench,
} from "lucide-react";
import { useMemo, useState } from "react";
import { ChatMarkdown } from "~/components/chat/chat-markdown";
import {
  openStandaloneNotebookArchive,
  type StandaloneChatRunStatus,
} from "~/lib/api";
import {
  RunActivityBlocks,
  RunTimeline,
  StepArtifactCardsContext,
  collectStepSequences,
} from "~/components/chat/run-timeline";
import { MessageRunContext } from "~/components/chat/message-run-context";
import { ConnectorSignInCards } from "~/components/chat/connector-signin-card";
import { RuntimeBootCard } from "~/components/chat/runtime-boot-card";
import { ReplayControls } from "~/components/chat/replay-controls";
import {
  deriveLiveStateFromBlocks,
  extractRuntimeBoot,
  foldRunBlocks,
  foldRunSteps,
  shouldShowRuntimeBoot,
} from "~/lib/chat-run-steps";
import { LivePill } from "~/components/chat/live-pill";
import { useChatReplay } from "~/lib/chat-replay";
import { useToast } from "~/components/ui/toast";
import {
  ChatUiContext,
  useChatUi,
  type UiMessage,
} from "~/components/chat/chat-ui-context";
import {
  DashboardPreviewCard,
  messageDashboardPreview,
} from "~/components/chat/chat-dashboard-preview-card";
import {
  deriveArtifactCards,
  groupCardsByAnchor,
} from "~/lib/chat-artifact-cards";
import {
  formatTelemetryClock,
  formatTelemetryDuration,
  formatTokenCount,
  estimateMessageTokens,
  parseChatTokenUsage,
  totalChatTokens,
} from "~/lib/chat-telemetry";
import { useChatTelemetryContext } from "~/components/chat/chat-telemetry-context";

function MessageTiming({
  message,
  previousMessageAt,
  running,
}: {
  message: UiMessage;
  previousMessageAt?: number;
  running?: boolean;
}) {
  const telemetry = useChatTelemetryContext();
  if (!telemetry.enabled) return null;
  const recordedAt = message.created_at * 1_000;
  const endAt = running ? telemetry.nowMs : recordedAt;
  const duration =
    message.role === "assistant" && previousMessageAt != null
      ? Math.max(0, endAt - previousMessageAt * 1_000)
      : null;
  const exact = new Date(recordedAt).toLocaleString();
  const estimatedTextTokens = estimateMessageTokens(message.content);
  const usage = parseChatTokenUsage(message.metadata.token_usage);
  const runTokens = totalChatTokens(usage);
  const usageTitle = usage
    ? [
        `Exact SDK run usage: ${runTokens.toLocaleString("en-US")} tokens`,
        `${(usage.input_tokens ?? 0).toLocaleString("en-US")} input`,
        `${(usage.output_tokens ?? 0).toLocaleString("en-US")} output`,
        `${(usage.cache_creation_input_tokens ?? 0).toLocaleString("en-US")} cache write`,
        `${(usage.cache_read_input_tokens ?? 0).toLocaleString("en-US")} cache read`,
      ].join(" · ")
    : "Estimated visible-text tokens; exact usage is only available at run completion";
  return (
    <span
      data-testid="chat-message-timing"
      className="inline-flex flex-wrap items-center gap-1.5 font-mono text-[10px] tabular-nums text-[var(--color-text-dim)] opacity-60 transition-opacity group-hover:opacity-100"
    >
      <span
        title={
          duration == null
            ? exact
            : `${exact} · response ${formatTelemetryDuration(duration)}`
        }
      >
        {formatTelemetryClock(recordedAt)}
        {duration != null ? ` · ${formatTelemetryDuration(duration)}` : ""}
      </span>
      <span aria-hidden>·</span>
      <span data-testid="chat-message-token-count" title={usageTitle}>
        ~{formatTokenCount(estimatedTextTokens)} text
        {usage ? ` · ${formatTokenCount(runTokens)} run tokens` : " tokens"}
      </span>
    </span>
  );
}

function WorkTimeline({ runId }: { runId: string }) {
  const { events } = useChatUi();
  const steps = useMemo(() => foldRunSteps(events, runId), [events, runId]);
  return <RunTimeline steps={steps} />;
}

function AssistantMessage({
  message,
  previousMessageAt,
  onReplay,
  replayMode = false,
}: {
  message: UiMessage;
  previousMessageAt?: number;
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
  const { events, files, onRetry, onStop } = useChatUi();
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
  const successful = runStatus === "completed";
  const running = runStatus === "queued" || runStatus === "running";
  // What the agent is doing right now: drives the caret, the inline
  // indicator and the footer pill. Idle whenever the run is not active.
  const live = useMemo(
    () => deriveLiveStateFromBlocks(blocks, runtimeBoot, runStatus),
    [blocks, runtimeBoot, runStatus],
  );
  // Artifact cards: every captured file gets one, placed in the timeline
  // right after the step that produced it (joined on the tool_started
  // sequence). Files no step claims trail the timeline. Derived from the
  // persisted events and manifest, so rehydration on refresh is free.
  const fileCards = useMemo(
    () => (runId ? deriveArtifactCards(events, files, runId, running) : []),
    [events, files, runId, running],
  );
  const anchoredCards = useMemo(
    () => groupCardsByAnchor(fileCards, collectStepSequences(steps)),
    [fileCards, steps],
  );
  const messageRun = useMemo(
    () => ({ runId: runId || null, running }),
    [runId, running],
  );
  const runtimeArchiveAvailable =
    message.metadata.runtime_archive_available === true;
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
        <MessageRunContext.Provider value={messageRun}>
        <StepArtifactCardsContext.Provider value={anchoredCards.byStep}>
        <div className="min-w-0 flex-1">
          {shouldShowRuntimeBoot(runtimeBoot, running) && runtimeBoot && (
            <RuntimeBootCard boot={runtimeBoot} />
          )}
          {(running ||
            blocks.length > 0 ||
            anchoredCards.trailing.length > 0) && (
            <div role="status" aria-live="polite">
              <RunActivityBlocks
                blocks={blocks}
                live={live}
                running={
                  running &&
                  runtimeBoot?.phase !== "provisioning" &&
                  runtimeBoot?.phase !== "resuming"
                }
                trailingCards={anchoredCards.trailing}
              />
            </div>
          )}
          {runId && <ConnectorSignInCards events={events} runId={runId} />}
          {!blocksHaveText && message.content && !messageRepeatsRunError && (
            <ChatMarkdown markdown={message.content} streaming={running} />
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
              <MessageTiming
                message={message}
                previousMessageAt={previousMessageAt}
                running={running}
              />
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
        </StepArtifactCardsContext.Provider>
        </MessageRunContext.Provider>
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
      <div className="mt-1 flex justify-end pr-1">
        <MessageTiming message={message} />
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
    conversationId,
    files,
    openArtifact,
    getFileObjectUrl,
    downloadFile,
    nowMs,
    onStop,
    onRetry,
  } = useChatUi();
  const replay = useChatReplay(events, runId);
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
          conversationId,
          files,
          openArtifact,
          getFileObjectUrl,
          downloadFile,
          nowMs,
          onStop,
          onRetry,
          onOpenDashboardPreview: () => undefined,
        }}
      >
        <AssistantMessage message={replayMessage} replayMode />
      </ChatUiContext.Provider>
    </div>
  );
}

function ReplayableAssistantMessage({
  message,
  previousMessageAt,
}: {
  message: UiMessage;
  previousMessageAt?: number;
}) {
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
      previousMessageAt={previousMessageAt}
      onReplay={canReplay ? () => setReplaying(true) : undefined}
    />
  );
}

export function ChatMessage({
  message,
  previousMessageAt,
}: {
  message: UiMessage;
  previousMessageAt?: number;
}) {
  return message.role === "user" ? (
    <UserMessage message={message} />
  ) : (
    <ReplayableAssistantMessage
      message={message}
      previousMessageAt={previousMessageAt}
    />
  );
}
