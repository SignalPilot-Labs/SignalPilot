"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, type ReactNode } from "react";
import { ExternalLink, Loader2, NotebookPen, X } from "lucide-react";
import {
  buildChatNotebookPopoutUrl,
  type LiveNotebookLink,
} from "~/lib/chat-live-notebook";
import { getStandaloneNotebookArchiveHtml } from "~/lib/api";

// The notebook runtime graph is heavy — load it only when a live link is
// actually shown, so /chats stays light until the agent starts a notebook.
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
 * Right-side panel on the standalone chat page that shows the notebook the
 * chat agent is working on.
 *
 * Document-first and kernel-free: the notebook inner view (read mode)
 * mounts INLINE from the best stored document; when the agent's kernel is
 * alive a kiosk websocket streams live updates on top. The sandboxed srcDoc
 * iframe of the static HTML archive remains only for legacy conversations
 * whose events carry no attach ids.
 */
export function LiveNotebookPanel({
  link,
  archiveRunId,
  onClose,
  liveViewOverride,
  archiveHtmlOverride,
}: {
  link: LiveNotebookLink | null;
  /** Legacy fallback: run id whose archived HTML to show when there is no link. */
  archiveRunId: string | null;
  onClose: () => void;
  /** Test-only: rendered instead of the live notebook view (fixture harness has no gateway). */
  liveViewOverride?: ReactNode;
  /** Test-only: archived notebook HTML, skipping the gateway fetch. */
  archiveHtmlOverride?: string;
}) {
  // Document-first: whenever a link exists the REAL notebook view renders —
  // kernel-free from the stored document, with the kiosk websocket as a
  // background enhancement. The static HTML archive iframe remains only for
  // legacy conversations whose events carry no attach ids.
  const showLive = Boolean(link);
  const showArchive = !showLive && Boolean(archiveRunId);
  const [archiveHtml, setArchiveHtml] = useState<string | null>(null);
  const [archiveError, setArchiveError] = useState(false);

  useEffect(() => {
    if (!showArchive || !archiveRunId || archiveHtmlOverride !== undefined) {
      setArchiveHtml(null);
      setArchiveError(false);
      return;
    }
    let cancelled = false;
    setArchiveError(false);
    getStandaloneNotebookArchiveHtml(archiveRunId)
      .then((html) => {
        if (!cancelled) setArchiveHtml(html);
      })
      .catch(() => {
        if (!cancelled) setArchiveError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [showArchive, archiveRunId, archiveHtmlOverride]);

  const resolvedArchiveHtml = showArchive
    ? (archiveHtmlOverride ?? archiveHtml)
    : null;

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
          {showLive && link?.live ? (
            <span
              data-testid="live-notebook-status-live"
              className="flex flex-none items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-emerald-600 dark:text-emerald-400"
            >
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
              Live
            </span>
          ) : showLive ? (
            <span
              data-testid="live-notebook-status-finished"
              className="flex-none rounded-full bg-[var(--color-bg-card)] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-[var(--color-text-dim)]"
            >
              Finished
            </span>
          ) : (
            <span
              data-testid="live-notebook-status-ended"
              className="flex-none rounded-full bg-[var(--color-bg-card)] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-[var(--color-text-dim)]"
            >
              {showArchive ? "Archived" : "Ended"}
            </span>
          )}
        </div>
        <div className="flex flex-none items-center gap-1">
          {link && showLive && (
            <a
              href={buildChatNotebookPopoutUrl(link)}
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
        {link && showLive ? (
          <div
            className="h-full w-full"
            data-testid="live-notebook-inline"
          >
            {liveViewOverride ?? (
              <ChatNotebookView
                gatewaySessionId={link.gatewaySessionId}
                kernelSessionId={link.kernelSessionId}
                notebookPath={link.notebookPath}
                runId={link.runId}
              />
            )}
          </div>
        ) : resolvedArchiveHtml != null ? (
          // Static archived HTML (scripts included for chart interactivity).
          // Sandboxed srcDoc iframe — the established pattern for rendering
          // generated HTML artifacts in the chat transcript.
          <iframe
            data-testid="archived-notebook-frame"
            title="Archived analysis notebook"
            sandbox="allow-scripts"
            srcDoc={resolvedArchiveHtml}
            className="h-full w-full border-0 bg-white"
          />
        ) : (
          <div
            data-testid="live-notebook-empty"
            className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center"
          >
            <NotebookPen className="h-6 w-6 text-[var(--color-text-dim)]" />
            <p className="text-sm text-[var(--color-text-muted)]">
              {archiveError
                ? "The archived notebook could not be loaded."
                : showArchive
                  ? "Loading the archived notebook…"
                  : link
                    ? "This notebook run has ended."
                    : "The agent hasn't started a notebook yet."}
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}
