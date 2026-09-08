"use client";

// Replay mode of the chat transcript: the whole conversation re-plays on
// one compressed clock. A sticky control bar sits above the transcript;
// below it, only the messages whose moment has been reached render, each
// assistant turn through the same AssistantMessage as live, fed by a
// nested chat UI context whose events, file manifest and clock follow the
// replay frame. The first time a file becomes ready while playing, the
// artifacts panel opens on it; while paused or scrubbed every visible
// text block renders complete, with no caret.

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import { ReplayControls } from "~/components/chat/replay-controls";
import {
  replayVisibleFiles,
  useConversationReplay,
  useReplayArtifactAutoOpen,
  type ConversationReplayState,
  canReplayConversation,
} from "~/lib/chat-replay";
import type { StandaloneChatEvent } from "~/lib/api";
import {
  ChatUiContext,
  useChatUi,
  type ChatUiContextValue,
  type UiMessage,
} from "~/components/chat/chat-ui-context";
import { AssistantMessage } from "~/components/chat/assistant-message";
import { useChatReplaySetting } from "~/components/chat/use-chat-replay-setting";
import { UserMessage } from "~/components/chat/chat-message";

/** Replay mode of one conversation; leaving the conversation leaves it.
 * `enabled` is the browser-local "Enable replay" chat setting: the pages
 * only offer the button when it is on. */
export function useReplayMode(
  conversationId: string | undefined,
  events: StandaloneChatEvent[],
  streaming: boolean,
) {
  const enabled = useChatReplaySetting();
  const [forConversation, setForConversation] = useState<string | null>(null);
  const replaying =
    Boolean(conversationId) && forConversation === conversationId;
  const canReplay =
    enabled &&
    Boolean(conversationId) &&
    !streaming &&
    !replaying &&
    canReplayConversation(events);
  const enterReplay = useCallback(
    () => setForConversation(conversationId ?? null),
    [conversationId],
  );
  const exitReplay = useCallback(() => setForConversation(null), []);
  return { canReplay, replaying, enterReplay, exitReplay };
}

/** Distance from the bottom under which the viewport counts as "at the
 * bottom" — the live page's stick-to-bottom rule. */
const STICK_THRESHOLD_PX = 96;

/**
 * Follow the newest content while playing, as a live chat does: scroll the
 * viewport to the bottom on every frame until the user scrolls up, and
 * resume once they return to the bottom. A restart follows again.
 */
function useReplayFollow(
  viewportRef: RefObject<HTMLDivElement | null> | undefined,
  replay: Pick<ConversationReplayState, "playing" | "session" | "elapsed">,
) {
  const stickRef = useRef(true);
  useEffect(() => {
    stickRef.current = true;
  }, [replay.session]);
  useEffect(() => {
    const viewport = viewportRef?.current;
    if (!viewport) return;
    const onScroll = () => {
      stickRef.current =
        viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <
        STICK_THRESHOLD_PX;
    };
    viewport.addEventListener("scroll", onScroll);
    return () => viewport.removeEventListener("scroll", onScroll);
  }, [viewportRef]);
  useLayoutEffect(() => {
    const viewport = viewportRef?.current;
    if (!viewport || !replay.playing || !stickRef.current) return;
    viewport.scrollTo({ top: viewport.scrollHeight });
  }, [viewportRef, replay.playing, replay.elapsed]);
}

export function ChatReplayView({
  messages,
  onExit,
  viewportRef,
}: {
  messages: UiMessage[];
  onExit: () => void;
  /** The scrolling transcript container, for the follow-the-stream rule. */
  viewportRef?: RefObject<HTMLDivElement | null>;
}) {
  const ui = useChatUi();
  const { events, files, openArtifact, nowMs } = ui;
  const source = useMemo(() => ({ messages, events }), [messages, events]);
  const replay = useConversationReplay(source);
  const { frame } = replay;
  const visibleFiles = useMemo(
    () =>
      replayVisibleFiles(files, {
        events,
        visibleEvents: frame.visibleEvents,
      }),
    [files, events, frame.visibleEvents],
  );
  useReplayArtifactAutoOpen({
    files: visibleFiles,
    runIds: frame.runIds,
    playing: replay.playing,
    session: replay.session,
    openArtifact,
  });
  useReplayFollow(viewportRef, replay);
  const replayUi = useMemo<ChatUiContextValue>(
    () => ({
      ...ui,
      events: frame.visibleEvents,
      files: visibleFiles,
      // The replay clock: relative timestamps measure from the instant the
      // frame shows, not from today. Falls back to the page's clock only
      // when nothing carries a parsable timestamp.
      nowMs: replay.nowMs ?? nowMs,
      textInstant: replay.textInstant,
    }),
    [ui, frame.visibleEvents, visibleFiles, replay.nowMs, replay.textInstant, nowMs],
  );
  return (
    <div data-testid="chat-replay" data-playing={replay.playing ? "1" : "0"}>
      <div className="sticky top-0 z-20 bg-[var(--color-bg)] px-6 pt-4">
        <div className="mx-auto w-full max-w-3xl">
          <ReplayControls
            elapsed={replay.elapsed}
            totalMs={replay.totalMs}
            playing={replay.playing}
            speed={replay.speed}
            onSpeedChange={replay.setSpeed}
            onTogglePlay={replay.togglePlay}
            onRestart={replay.restart}
            onScrub={replay.scrub}
            onExit={onExit}
          />
        </div>
      </div>
      <ChatUiContext.Provider value={replayUi}>
        <div data-testid="chat-replay-messages" className="pb-8">
          {frame.messages.map((message, index) =>
            message.role === "user" ? (
              <UserMessage key={message.id} message={message} />
            ) : (
              <AssistantMessage
                key={message.id}
                message={message}
                previousMessageAt={frame.messages[index - 1]?.created_at}
                replayMode
              />
            ),
          )}
        </div>
      </ChatUiContext.Provider>
    </div>
  );
}
