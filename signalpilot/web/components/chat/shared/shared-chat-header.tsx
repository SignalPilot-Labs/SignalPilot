"use client";

import { ArrowLeft, GitFork, History, Loader2, LockKeyhole } from "lucide-react";
import type { SharedConversation } from "~/lib/api";
import { AutomatedBadge } from "~/components/chat/standalone-chat-helpers";

/**
 * Header of the read-only shared chat page: title, project, a "shared with
 * your team" label, "Replay chat" when there is something to replay, and
 * the one primary action, "Fork to my chats".
 */
export function SharedChatHeader({
  conversation,
  forkingEnabled,
  forking,
  onFork,
  onBack,
  onReplay,
}: {
  conversation: SharedConversation;
  forkingEnabled: boolean;
  forking: boolean;
  onFork: () => void;
  onBack: () => void;
  /** Offered only when the conversation has something to replay. */
  onReplay?: () => void;
}) {
  return (
    <header
      data-testid="shared-chat-header"
      className="flex h-16 flex-none items-center justify-between gap-4 border-b border-[var(--color-border)] px-6"
    >
      <div className="flex min-w-0 items-center gap-3">
        <button
          type="button"
          aria-label="Back to your chats"
          onClick={onBack}
          className="rounded-lg p-2 text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.15em] text-[var(--color-text-dim)]">
            <LockKeyhole className="h-3 w-3" />
            Shared with your team · read only
          </div>
          <div className="flex min-w-0 items-center gap-2">
            <div
              data-testid="shared-chat-title"
              className="max-w-xl truncate text-sm text-[var(--color-text)]"
            >
              {conversation.title}
            </div>
            {conversation.origin === "improvement" && <AutomatedBadge />}
          </div>
        </div>
      </div>
      <div className="flex flex-none items-center gap-3">
        {conversation.project_name && (
          <span className="text-xs text-[var(--color-text-dim)]">
            {conversation.project_name}
          </span>
        )}
        {onReplay && (
          <button
            type="button"
            data-testid="chat-replay-button"
            aria-label="Replay chat"
            title="Replay this conversation as it happened"
            onClick={onReplay}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
          >
            <History className="h-3.5 w-3.5" />
            Replay chat
          </button>
        )}
        {forkingEnabled && (
          <button
            type="button"
            data-testid="shared-chat-fork"
            disabled={forking}
            onClick={onFork}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--color-text)] px-3 py-2 text-xs text-[var(--color-bg)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {forking ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <GitFork className="h-3.5 w-3.5" />
            )}
            Fork to my chats
          </button>
        )}
      </div>
    </header>
  );
}
