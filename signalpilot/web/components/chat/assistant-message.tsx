"use client";

// The assistant turn of the standalone data chat transcript: activity
// blocks, inline artifact cards, the answer and the action row. Rendered
// live by chat-message.tsx and again, on the compressed replay clock, by
// chat-replay-view.tsx.

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
import {
  deriveLiveStateFromBlocks,
  extractRuntimeBoot,
  foldRunBlocks,
  foldRunSteps,
  shouldShowRuntimeBoot,
} from "~/lib/chat-run-steps";
import { LivePill } from "~/components/chat/live-pill";
import { useToast } from "~/components/ui/toast";
import { useChatUi, type UiMessage } from "~/components/chat/chat-ui-context";
import {
  deriveArtifactCards,
  groupCardsByAnchor,
} from "~/lib/chat-artifact-cards";
import { MessageTiming } from "~/components/chat/chat-message-timing";
import { ChatErrorDetails } from "~/components/chat/chat-error-details";

function WorkTimeline({ runId }: { runId: string }) {
  const { events } = useChatUi();
  const steps = useMemo(() => foldRunSteps(events, runId), [events, runId]);
  return <RunTimeline steps={steps} />;
}

const ACTION_BUTTON =
  "inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]";

export function AssistantMessage({
  message,
  previousMessageAt,
  replayMode = false,
}: {
  message: UiMessage;
  previousMessageAt?: number;
  /** Rendered by the conversation replay: no action row. */
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
  const ui = useChatUi();
  const { events, files, onRetry, onStop } = ui;
  // A read-only surface (the shared page) keeps Copy and Replay but has no
  // run to stop or retry. Read defensively: the flag is optional.
  const readOnly = ui.readOnly === true;
  // Replay paused or scrubbed: text renders complete, with no caret.
  const textInstant = ui.textInstant === true;
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
                instantText={textInstant}
              />
            </div>
          )}
          {runId && <ConnectorSignInCards events={events} runId={runId} />}
          {runId && <ChatErrorDetails events={events} runId={runId} />}
          {!blocksHaveText && message.content && !messageRepeatsRunError && (
            <ChatMarkdown markdown={message.content} streaming={running} />
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
                  className={ACTION_BUTTON}
                >
                  <Copy className="h-3 w-3" />
                  Copy
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
                  className={ACTION_BUTTON}
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
              {running && runId && !readOnly && (
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
              {runStatus === "failed" && runId && !readOnly && (
                <button
                  type="button"
                  onClick={() => void onRetry(runId)}
                  className={ACTION_BUTTON}
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
