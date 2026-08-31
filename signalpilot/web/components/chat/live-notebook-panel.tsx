"use client";

import dynamic from "next/dynamic";
import type { ReactNode } from "react";
import { ExternalLink, Loader2, NotebookPen, X } from "lucide-react";
import {
  buildChatNotebookPopoutUrl,
  chatNotebookMountKey,
} from "~/lib/chat-live-notebook";
import type { ConversationNotebook } from "~/lib/api";

// The notebook runtime graph is heavy. Load it only when the panel shows a
// notebook, so /chats stays light until then.
const ChatNotebookView = dynamic(
  () => import("~/components/chat/chat-notebook-view"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
      </div>
    ),
  },
);

/**
 * Right-side panel on the chat page that shows the conversation's analysis
 * notebook.
 *
 * The panel renders the gateway's notebook resource as-is. "Live" means the
 * gateway verified the kernel sandbox is running; anything else renders the
 * saved document with a "Finished" badge.
 */
export function LiveNotebookPanel({
  conversationId,
  notebook,
  onClose,
  liveViewOverride,
}: {
  conversationId: string;
  notebook: ConversationNotebook | null;
  onClose: () => void;
  /** Test-only: rendered instead of the notebook view (the fixture harness has no gateway). */
  liveViewOverride?: ReactNode;
}) {
  const live = notebook?.status === "live";
  const showNotebook = Boolean(
    notebook && (live || notebook.document !== null),
  );

  return (
    <aside
      data-testid="live-notebook-panel"
      className="flex w-[46%] min-w-[420px] max-w-[820px] flex-none flex-col border-l border-[var(--color-border)] bg-[var(--color-bg)]"
    >
      <div className="flex h-11 flex-none items-center justify-between border-b border-[var(--color-border)] px-3">
        <div className="flex min-w-0 items-center gap-2">
          <NotebookPen className="h-3.5 w-3.5 flex-none text-[var(--color-text-dim)]" />
          <span className="truncate text-xs font-medium text-[var(--color-text)]">
            Analysis notebook
          </span>
          {live ? (
            <span
              data-testid="live-notebook-status-live"
              className="flex flex-none items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-emerald-600 dark:text-emerald-400"
            >
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
              Live
            </span>
          ) : (
            <span
              data-testid="live-notebook-status-finished"
              className="flex-none rounded-full bg-[var(--color-bg-card)] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-[var(--color-text-dim)]"
            >
              Finished
            </span>
          )}
        </div>
        <div className="flex flex-none items-center gap-1">
          {showNotebook && (
            <a
              href={buildChatNotebookPopoutUrl(conversationId)}
              target="_blank"
              rel="noopener noreferrer"
              title="Open notebook in a new tab"
              aria-label="Open notebook in a new tab"
              data-testid="live-notebook-popout"
              className="rounded p-1.5 text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
          <button
            type="button"
            onClick={onClose}
            title="Close notebook panel"
            aria-label="Close notebook panel"
            data-testid="live-notebook-close"
            className="rounded p-1.5 text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <div className="relative min-h-0 flex-1" data-testid="live-notebook-body">
        {showNotebook && notebook ? (
          <div className="h-full w-full" data-testid="live-notebook-inline">
            {liveViewOverride ?? (
              <ChatNotebookView
                key={chatNotebookMountKey(notebook)}
                notebook={notebook}
              />
            )}
          </div>
        ) : (
          <div
            data-testid="live-notebook-empty"
            className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center"
          >
            <NotebookPen className="h-6 w-6 text-[var(--color-text-dim)]" />
            <p className="text-sm text-[var(--color-text-muted)]">
              The agent hasn&apos;t started a notebook yet.
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}
