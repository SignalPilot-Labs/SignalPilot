"use client";

// The shared chat page IS the chat page, read only: the same message tree,
// inline artifact cards, and artifacts panel as the owner sees, fed by the
// share-token routes. One button forks the whole chat into the viewer's own.

import { AlertCircle, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { ArtifactsPanel } from "~/components/chat/artifacts-panel";
import { ChatMessage } from "~/components/chat/chat-message";
import { ChatReplayView } from "~/components/chat/chat-replay-view";
import { ChatUiContext } from "~/components/chat/chat-ui-context";
import { SharedChatHeader } from "~/components/chat/shared/shared-chat-header";
import {
  useForkSharedChat,
  useSharedChat,
  useSharedChatUi,
} from "~/components/chat/shared/use-shared-chat";
import { chatShellClassName } from "~/components/chat/standalone-chat-derivations";
import { ChatPanelToggles } from "~/components/chat/standalone-chat-panels";
import { useOpenArtifact } from "~/components/chat/use-open-artifact";
import { hasArtifactsContent } from "~/lib/chat-artifacts";
import { canReplayConversation } from "~/lib/chat-replay";
import { useChatReplaySetting } from "~/components/chat/use-chat-replay-setting";
import { standaloneMessageKey } from "~/lib/standalone-chat-state";

function SharedChatUnavailable({ onBack }: { onBack: () => void }) {
  return (
    <div className="flex h-screen items-center justify-center p-8">
      <div className="max-w-md rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6 text-center">
        <AlertCircle className="mx-auto h-5 w-5 text-[var(--color-text-dim)]" />
        <h1 className="mt-3 text-base text-[var(--color-text)]">
          Shared conversation unavailable
        </h1>
        <p className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">
          This link is invalid, revoked, archived, or belongs to another
          organization.
        </p>
        <button
          type="button"
          onClick={onBack}
          className="mt-4 rounded-lg border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
        >
          Go to your chats
        </button>
      </div>
    </div>
  );
}

/**
 * Blocks the page while the gateway copies the chat. Forking a long chat
 * with many files takes several seconds, and the redirect to the new chat
 * only happens when it is done, so the wait must be visible.
 */
function ForkingOverlay() {
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="shared-chat-forking"
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70"
    >
      <div className="flex items-center gap-3 rounded-[14px] border border-[var(--color-border)] bg-[var(--color-bg-card)] px-5 py-4 shadow-2xl animate-scale-in">
        <Loader2 className="h-4 w-4 animate-spin text-[var(--color-success)]" />
        <div>
          <div className="text-[13px] font-medium text-[var(--color-text)]">
            Copying this chat into your workspace
          </div>
          <div className="mt-0.5 text-xs text-[var(--color-text-muted)]">
            Messages, work timeline, and files. You will land on your copy
            when it is ready.
          </div>
        </div>
      </div>
    </div>
  );
}

export function SharedStandaloneDataChat({ token }: { token: string }) {
  const replayEnabled = useChatReplaySetting();
  const router = useRouter();
  const goToChats = useCallback(() => router.push("/chats"), [router]);
  const { detail, error, isLoading, uiMessages, executions, forkingEnabled } =
    useSharedChat(token);
  const { forking, fork } = useForkSharedChat(token);
  const [artifactsOpen, setArtifactsOpen] = useState(false);
  const openArtifactsPanel = useCallback(() => setArtifactsOpen(true), []);
  const { openFileRequest, openArtifact } = useOpenArtifact(openArtifactsPanel);
  const ui = useSharedChatUi(token, detail, openArtifact);
  const [replaying, setReplaying] = useState(false);
  const viewportRef = useRef<HTMLDivElement | null>(null);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
      </div>
    );
  }
  if (error || !detail) {
    return <SharedChatUnavailable onBack={goToChats} />;
  }

  const files = detail.files;
  const artifactsAvailable = hasArtifactsContent([], files, executions);

  return (
    <ChatUiContext.Provider value={ui}>
      {forking && <ForkingOverlay />}
      <div className={chatShellClassName(false, false, artifactsOpen)}>
        <div className="relative flex h-full overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg)] shadow-2xl shadow-black/20">
          <main className="relative flex min-w-0 flex-1 flex-col">
            <SharedChatHeader
              conversation={detail.conversation}
              forkingEnabled={forkingEnabled}
              forking={forking}
              onFork={() => void fork()}
              onBack={goToChats}
              onReplay={
                replayEnabled && canReplayConversation(ui.events) && !replaying
                  ? () => setReplaying(true)
                  : undefined
              }
            />
            <div className="relative flex min-h-0 flex-1 flex-col">
              <div ref={viewportRef} className="min-h-0 flex-1 overflow-y-auto">
                {replaying ? (
                  <ChatReplayView
                    messages={uiMessages}
                    onExit={() => setReplaying(false)}
                    viewportRef={viewportRef}
                  />
                ) : (
                  <div data-testid="standalone-chat-messages" className="pb-8">
                    {uiMessages.map((message, index) => (
                      <ChatMessage
                        key={standaloneMessageKey(undefined, message)}
                        message={message}
                        previousMessageAt={uiMessages[index - 1]?.created_at}
                      />
                    ))}
                  </div>
                )}
              </div>
              <ChatPanelToggles
                artifactsAvailable={artifactsAvailable}
                artifactsLoading={false}
                artifactsOpen={artifactsOpen}
                onOpenArtifacts={openArtifactsPanel}
              />
            </div>
          </main>
          {artifactsOpen && (
            <ArtifactsPanel
              conversationId=""
              notebooks={[]}
              files={files}
              executions={executions}
              openFileRequest={openFileRequest}
              onClose={() => setArtifactsOpen(false)}
            />
          )}
        </div>
      </div>
    </ChatUiContext.Provider>
  );
}
