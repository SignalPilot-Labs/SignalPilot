"use client";

// Presentational parts of the standalone data chat page:
// conversation rail, empty-state helpers, approval card, and skeletons.

import {
  AlertCircle,
  Loader2,
  MessageSquarePlus,
  MoreHorizontal,
  Share2,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import type {
  StandaloneChatEvent,
  StandaloneConversation,
} from "~/lib/api";
import {
  AutomatedBadge,
  eventText,
  isImprovementConversation,
  statusLabel,
  statusTone,
} from "~/components/chat/standalone-chat-helpers";

export function StarterQuestions({
  questions,
  onSelect,
}: {
  questions: string[];
  onSelect: (question: string) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {questions.slice(0, 4).map((question) => (
        <button
          key={question}
          type="button"
          onClick={() => {
            onSelect(question);
            requestAnimationFrame(() =>
              document
                .querySelector<HTMLTextAreaElement>("[data-chat-composer]")
                ?.focus(),
            );
          }}
          className="min-h-24 rounded-xl border border-[var(--color-border)] bg-[#1a1a1d] p-4 text-left text-[14.5px] leading-6 text-[var(--color-text-muted)] transition-colors hover:border-[var(--color-border-hover)] hover:bg-[#212125] hover:text-[var(--color-text)]"
        >
          {question}
        </button>
      ))}
    </div>
  );
}

export function ReadinessNotice({
  message,
  showSetup,
  onSetup,
}: {
  message: string;
  showSetup: boolean;
  onSetup: () => void;
}) {
  return (
    <div className="rounded-xl border border-[var(--color-warning)]/20 bg-[var(--color-bg-card)] p-4 text-sm text-[var(--color-warning)]">
      <p>{message}</p>
      {showSetup && (
        <button
          type="button"
          onClick={onSetup}
          className="mt-3 rounded-lg border border-[var(--color-warning)]/30 px-3 py-1.5 text-xs hover:bg-[var(--color-bg-hover)]"
        >
          Open project setup
        </button>
      )}
    </div>
  );
}

export function ConversationRail({
  conversations,
  activeId,
  historyLoading,
  loadingConversationId,
  onNewConversation,
  onSelectConversation,
  onPrefetchConversation,
  onRename,
  onArchive,
  onShare,
  onRevokeShare,
  sharingEnabled,
}: {
  conversations: StandaloneConversation[];
  activeId?: string;
  historyLoading: boolean;
  loadingConversationId: string | null;
  onNewConversation: () => void;
  onSelectConversation: (conversationId: string) => void;
  onPrefetchConversation: (conversationId: string) => void;
  onRename: (conversation: StandaloneConversation) => void;
  onArchive: (conversation: StandaloneConversation) => void;
  onShare: (conversation: StandaloneConversation) => void;
  onRevokeShare: (conversation: StandaloneConversation) => void;
  sharingEnabled: boolean;
}) {
  const [menuId, setMenuId] = useState<string | null>(null);
  return (
    <aside className="flex w-72 flex-none flex-col border-r border-[var(--color-border)] bg-[var(--color-sidebar)]">
      <div className="p-3 pr-7">
        <button
          type="button"
          onClick={onNewConversation}
          className="flex w-full items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-2.5 text-sm text-[var(--color-text)] hover:border-[var(--color-border-hover)]"
        >
          <MessageSquarePlus className="h-4 w-4" />
          New chat
        </button>
      </div>
      <div className="px-3 pb-2 text-[10px] uppercase tracking-[0.16em] text-[var(--color-text-dim)]">
        Your chats
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {historyLoading && conversations.length === 0 ? (
          <div
            aria-label="Loading chat history"
            role="status"
            className="space-y-2 px-2 py-1"
          >
            {[0, 1, 2, 3].map((index) => (
              <div
                key={index}
                className="h-14 animate-pulse rounded-xl bg-[var(--color-bg-card)]"
              />
            ))}
          </div>
        ) : conversations.length === 0 ? (
          <p className="px-3 py-4 text-xs text-[var(--color-text-dim)]">
            Your private conversations will appear here.
          </p>
        ) : (
          conversations.map((conversation) => (
            <div
              key={conversation.id}
              className={`group relative mb-1 rounded-xl ${
                conversation.id === activeId
                  ? "bg-[var(--color-bg-hover)]"
                  : "hover:bg-[var(--color-bg-card)]"
              }`}
            >
              <button
                type="button"
                onPointerEnter={() => onPrefetchConversation(conversation.id)}
                onFocus={() => onPrefetchConversation(conversation.id)}
                onClick={() => onSelectConversation(conversation.id)}
                className="w-full px-3 py-2.5 pr-9 text-left"
              >
                <div className="flex items-center gap-2 text-[13px] text-[var(--color-text)]">
                  <span className="min-w-0 flex-1 truncate">
                    {conversation.title}
                  </span>
                  {isImprovementConversation(conversation) && (
                    <AutomatedBadge />
                  )}
                  {loadingConversationId === conversation.id && (
                    <Loader2 className="h-3 w-3 flex-none animate-spin text-[var(--color-text-dim)]" />
                  )}
                </div>
                <div className="mt-1 flex items-center gap-2 text-[10px]">
                  <span className="truncate text-[var(--color-text-dim)]">
                    {conversation.project_name}
                  </span>
                  {conversation.run_status && (
                    <span className={statusTone(conversation.run_status)}>
                      {statusLabel(conversation.run_status)}
                    </span>
                  )}
                </div>
              </button>
              <button
                type="button"
                aria-label="Conversation actions"
                onClick={() =>
                  setMenuId((value) =>
                    value === conversation.id ? null : conversation.id,
                  )
                }
                className="absolute right-2 top-2 rounded-md p-1 text-[var(--color-text-dim)] opacity-0 hover:bg-[var(--color-bg-elevated)] hover:text-[var(--color-text)] group-hover:opacity-100"
              >
                <MoreHorizontal className="h-3.5 w-3.5" />
              </button>
              {menuId === conversation.id && (
                <div className="absolute right-2 top-9 z-20 w-44 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-1 shadow-2xl">
                  {sharingEnabled && (
                    <button
                      type="button"
                      onClick={() => {
                        setMenuId(null);
                        onShare(conversation);
                      }}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                    >
                      <Share2 className="h-3 w-3" />
                      Share with team
                    </button>
                  )}
                  {sharingEnabled && (
                    <button
                      type="button"
                      onClick={() => {
                        setMenuId(null);
                        onRevokeShare(conversation);
                      }}
                      className="w-full rounded-lg px-3 py-2 text-left text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                    >
                      Revoke team link
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      setMenuId(null);
                      onRename(conversation);
                    }}
                    className="w-full rounded-lg px-3 py-2 text-left text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                  >
                    Rename
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMenuId(null);
                      onArchive(conversation);
                    }}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-[var(--color-error)] hover:bg-[var(--color-bg-hover)]"
                  >
                    <Trash2 className="h-3 w-3" />
                    Remove from history
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>
      <div className="border-t border-[var(--color-border)] px-4 py-3 text-[10px] leading-4 text-[var(--color-text-dim)]">
        Private to you · automatically saved
      </div>
    </aside>
  );
}

export function QueryApprovalCard({
  event,
  onDecision,
}: {
  event: StandaloneChatEvent;
  onDecision: (
    decision: "approve" | "decline",
    scope?: "run_once" | "current_chat" | "user_defaults",
  ) => Promise<void>;
}) {
  const purpose = eventText(event, "purpose") || "Run the proposed query";
  const estimate = Number(event.payload.estimated_cost_usd ?? 0);
  const remaining = Number(event.payload.remaining_chat_budget_usd ?? 0);
  const quality =
    eventText(event, "estimate_quality") || "estimate unavailable";
  return (
    <section
      role="status"
      aria-live="polite"
      aria-label="Query approval required"
      className="mx-auto mb-2 w-full max-w-3xl rounded-xl border border-[var(--color-warning)]/40 bg-[var(--color-bg-card)] p-4"
    >
      <p className="text-sm font-medium text-[var(--color-text)]">
        Query approval required
      </p>
      <p className="mt-1 text-xs text-[var(--color-text-muted)]">{purpose}</p>
      <div className="mt-3 flex gap-5 text-xs text-[var(--color-text-dim)]">
        <span>Estimated cost: ${estimate.toFixed(4)}</span>
        <span>Remaining chat budget: ${remaining.toFixed(4)}</span>
        <span>Quality: {quality.replaceAll("_", " ")}</span>
      </div>
      <details className="mt-3 text-xs text-[var(--color-text-dim)]">
        <summary>Technical details</summary>
        <code className="mt-2 block break-all">
          SQL hash: {eventText(event, "sql_hash")}
        </code>
      </details>
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void onDecision("approve", "run_once")}
          className="rounded-lg bg-[var(--color-text)] px-3 py-2 text-xs text-[var(--color-bg)]"
        >
          Run once
        </button>
        <button
          type="button"
          onClick={() => void onDecision("approve", "current_chat")}
          className="rounded-lg border border-[var(--color-border)] px-3 py-2 text-xs"
        >
          Increase this chat budgets
        </button>
        <button
          type="button"
          onClick={() => void onDecision("approve", "user_defaults")}
          className="rounded-lg border border-[var(--color-border)] px-3 py-2 text-xs"
        >
          Use as future defaults
        </button>
        <button
          type="button"
          onClick={() => void onDecision("decline")}
          className="rounded-lg px-3 py-2 text-xs text-[var(--color-error)]"
        >
          Decline
        </button>
      </div>
    </section>
  );
}

export function ConversationMessagesSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading conversation"
      className="mx-auto flex min-h-full w-full max-w-3xl flex-col justify-end gap-5 px-6 py-10"
    >
      <div className="ml-auto h-12 w-2/5 animate-pulse rounded-2xl bg-[var(--color-bg-card)]" />
      <div className="flex max-w-2xl items-start gap-3">
        <Loader2 className="mt-1 h-4 w-4 flex-none animate-spin text-[var(--color-text-dim)]" />
        <div className="w-full space-y-2">
          <div className="h-3 w-5/6 animate-pulse rounded bg-[var(--color-bg-card)]" />
          <div className="h-3 w-2/3 animate-pulse rounded bg-[var(--color-bg-card)]" />
          <div className="h-3 w-3/4 animate-pulse rounded bg-[var(--color-bg-card)]" />
        </div>
      </div>
      <span className="sr-only">Loading conversation</span>
    </div>
  );
}

export function ChatBootstrapSpinner() {
  return (
    <div className="flex h-screen items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
    </div>
  );
}

export function ChatUnavailableScreen() {
  return (
    <div className="flex h-screen items-center justify-center p-8">
      <div className="max-w-md rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6 text-center">
        <AlertCircle className="mx-auto mb-3 h-5 w-5 text-[var(--color-text-dim)]" />
        <h1 className="text-base text-[var(--color-text)]">
          Data chat is unavailable
        </h1>
        <p className="mt-2 text-sm text-[var(--color-text-muted)]">
          Ask an administrator to enable standalone data chat.
        </p>
      </div>
    </div>
  );
}

export function ConversationNotFoundScreen({
  onNewChat,
}: {
  onNewChat: () => void;
}) {
  return (
    <div className="flex h-screen items-center justify-center p-8">
      <div className="max-w-md rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6 text-center">
        <AlertCircle className="mx-auto mb-3 h-5 w-5 text-[var(--color-error)]" />
        <h1 className="text-base text-[var(--color-text)]">
          Conversation not found
        </h1>
        <p className="mt-2 text-sm text-[var(--color-text-muted)]">
          This conversation does not exist or is not available to your
          account.
        </p>
        <button
          type="button"
          onClick={onNewChat}
          className="mt-4 rounded-lg border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text)]"
        >
          Start a new chat
        </button>
      </div>
    </div>
  );
}

/** Banner above the transcript: the report attached to the next message. */
export function AttachedReportBanner({
  title,
  onRemove,
}: {
  title: string;
  onRemove: () => void;
}) {
  return (
    <div className="flex-none px-6 pt-4">
      <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 rounded-xl border border-[var(--color-success)]/25 bg-[var(--color-bg-card)] px-4 py-3 text-xs text-[var(--color-text-muted)]">
        <span>@{title} is attached to your next message.</span>
        <button
          type="button"
          onClick={onRemove}
          className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
        >
          Remove
        </button>
      </div>
    </div>
  );
}

/** Placeholder grid while the four starter questions load. */
export function StarterQuestionsSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3">
      {[0, 1, 2, 3].map((index) => (
        <div
          key={index}
          className="h-24 animate-pulse rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]"
        />
      ))}
    </div>
  );
}
