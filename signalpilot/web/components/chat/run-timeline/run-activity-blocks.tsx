"use client";

import { Brain, ChevronRight } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { AgentLiveIndicator } from "~/components/chat/agent-thinking-indicator";
import { ChatMarkdown } from "~/components/chat/chat-markdown";
import { useSettled } from "~/components/chat/use-settled";
import { useSmoothedStreamingText } from "~/components/chat/use-smoothed-streaming-text";
import {
  shouldShowAgentThinking,
  type RunBlock,
  type RunLiveInfo,
} from "~/lib/chat-run-steps";
import type { ArtifactCardModel } from "~/lib/chat-artifact-cards";
import { ActivityGroup } from "./activity-group";
import { ArtifactCardBlock } from "./step-artifact-cards";

const IDLE_LIVE: RunLiveInfo = { state: "idle", label: "", step: null };
const THINKING_LIVE: RunLiveInfo = {
  state: "thinking",
  label: "Thinking",
  step: null,
};

/** How long the caret lingers after the last token, so it fades, not pops. */
const CARET_SETTLE_MS = 400;

function StreamingTextBlock({
  text,
  streaming,
  flush,
  caret,
}: {
  text: string;
  streaming: boolean;
  flush: boolean;
  caret: boolean | "fading";
}) {
  const smoothed = useSmoothedStreamingText({ text, streaming, flush });
  const active = streaming || smoothed.smoothing;
  const caretSettled = useSettled(active, CARET_SETTLE_MS);
  const effectiveCaret: boolean | "fading" = active
    ? true
    : caretSettled
      ? "fading"
      : caret;
  return (
    <ChatMarkdown
      markdown={smoothed.text}
      className="my-3"
      streaming={active}
      caret={effectiveCaret}
    />
  );
}

/**
 * A stretch of the model's extended thinking. Streams open with a live
 * shimmer while tokens arrive, then folds down to a quiet one-line toggle
 * so reasoning is inspectable without crowding the answer.
 */
export function ThinkingBlockView({ text, live }: { text: string; live: boolean }) {
  const [userToggle, setUserToggle] = useState<boolean | null>(null);
  // Streaming shows the thought as it forms; once done it folds closed.
  useEffect(() => {
    if (live) setUserToggle(null);
  }, [live]);
  const open = userToggle ?? live;
  return (
    <section
      data-testid="chat-thinking-block"
      className="my-3"
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setUserToggle(!open)}
        className="flex items-center gap-2 rounded-md px-1 py-0.5 text-left text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-muted)]"
      >
        <Brain className="h-3.5 w-3.5 flex-none" />
        <span className={live ? "chat-live-label font-medium" : ""}>
          {live ? "Thinking…" : "Thought process"}
        </span>
        <ChevronRight
          className={`h-3 w-3 flex-none transition-transform ${open ? "rotate-90" : ""}`}
        />
      </button>
      <div className="chat-collapse" data-open={open}>
        <div>
          <div className="mt-1.5 max-h-64 overflow-y-auto border-l-2 border-[var(--color-border)] py-0.5 pl-3 pr-1">
            <p className="chat-thinking-text text-[12px] leading-5 text-[var(--color-text-dim)] italic">
              {text}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

/**
 * Full interleaved view of a run: markdown for streamed narration, an
 * ActivityGroup per tool chain, in the order they actually happened. Only
 * the trailing group is treated as live while the run streams.
 *
 * `live` is the derived agent state; it drives the caret on the trailing
 * text block and the inline indicator. `running` is kept for callers that
 * only know whether the run is active — it defaults from `live`, and when
 * given alone it implies a thinking state.
 */
export function RunActivityBlocks({
  blocks,
  running: runningProp,
  live: liveProp,
  trailingCards = [],
}: {
  blocks: RunBlock[];
  running?: boolean;
  live?: RunLiveInfo;
  /** Cards no step claims; rendered after the last tool group. */
  trailingCards?: ArtifactCardModel[];
}) {
  const live =
    liveProp ?? (runningProp ? THINKING_LIVE : IDLE_LIVE);
  // Booting is the runtime card's moment; the transcript stays quiet.
  const running =
    runningProp ?? (live.state !== "idle" && live.state !== "booting");
  const writing = running && live.state === "writing";
  // The caret lingers after the last token and exits with chat-caret-out
  // instead of disappearing on the exact frame the stream ends.
  const caretShown = useSettled(writing, CARET_SETTLE_MS);
  const caret: boolean | "fading" = writing
    ? true
    : caretShown
      ? "fading"
      : false;
  const showThinking =
    shouldShowAgentThinking(blocks, running) &&
    (live.state === "thinking" || live.state === "booting");
  const trailing = (
    <ArtifactCardBlock
      cards={trailingCards}
      testId="chat-trailing-artifact-cards"
      className="my-3"
    />
  );
  if (!blocks.length) {
    return (
      <>
        {trailing}
        {showThinking && <AgentLiveIndicator live={live} />}
      </>
    );
  }
  const lastStepsIndex = blocks.reduce(
    (latest, block, index) => (block.kind === "steps" ? index : latest),
    -1,
  );
  const trailingSteps =
    lastStepsIndex === blocks.length - 1 && lastStepsIndex >= 0;
  return (
    <>
      {/* No tool group at all: the unclaimed files lead the narration. */}
      {lastStepsIndex === -1 && trailing}
      {blocks.map((block, index) =>
        block.kind === "text" ? (
          <StreamingTextBlock
            key={block.key}
            text={block.text}
            streaming={running && index === blocks.length - 1}
            flush={index !== blocks.length - 1}
            caret={index === blocks.length - 1 ? caret : false}
          />
        ) : block.kind === "thinking" ? (
          <ThinkingBlockView
            key={block.key}
            text={block.text}
            live={running && index === blocks.length - 1}
          />
        ) : (
          <Fragment key={block.key}>
            <ActivityGroup
              steps={block.steps}
              live={running && trailingSteps && index === lastStepsIndex}
              isFinalGroup={index === lastStepsIndex}
              runCompleted={!running}
            />
            {index === lastStepsIndex && trailing}
          </Fragment>
        ),
      )}
      {showThinking && <AgentLiveIndicator live={live} />}
    </>
  );
}
