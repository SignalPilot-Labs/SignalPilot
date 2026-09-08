"use client";

// Centered dialog shown right after a chat is shared. It puts the link in
// front of the user with a copy action and states plainly who can open it:
// signed-in members of this organization, nobody else, ever.

import { CheckCircle2, Copy, Loader2, LockKeyhole, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useFocusTrap } from "~/components/ui/use-focus-trap";

export function ShareLinkDialog({
  url: link,
  onClose,
}: {
  /** The share URL; "pending" shows the dialog with a loader while the
   * gateway mints the link; null hides it. */
  url: string | "pending" | null;
  onClose: () => void;
}) {
  const open = link !== null;
  const pending = link === "pending";
  const url = pending ? null : link;
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState(false);
  useFocusTrap(panelRef, open);

  const copy = useCallback(async () => {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // Clipboard blocked: leave the link selected so Ctrl+C works.
      inputRef.current?.select();
    }
  }, [url]);

  // Copy on open so the common case is one click; the button re-copies.
  useEffect(() => {
    if (!open) {
      setCopied(false);
      return;
    }
    if (!url) return;
    void copy();
    inputRef.current?.select();
  }, [open, url, copy]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70"
      onClick={onClose}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="share-link-title"
        data-testid="share-link-dialog"
        className="w-[520px] max-w-[92vw] overflow-hidden rounded-[14px] border border-[var(--color-border)] bg-[var(--color-bg-card)] shadow-2xl animate-scale-in"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-5 py-3">
          <span
            id="share-link-title"
            className="text-[13px] font-medium text-[var(--color-text)]"
          >
            Share this chat with your team
          </span>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded-lg p-1.5 text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-5 py-4">
          <p className="text-xs leading-relaxed text-[var(--color-text-muted)]">
            Teammates who open this link see the whole chat, including the
            work timeline and every file it produced, and can fork it into
            their own chats.
          </p>
          {pending ? (
            <div
              data-testid="share-link-pending"
              role="status"
              aria-live="polite"
              className="mt-3 flex items-center gap-3 rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-3 text-xs text-[var(--color-text-muted)]"
            >
              <Loader2 className="h-4 w-4 flex-none animate-spin text-[var(--color-success)]" />
              Generating your team link. Any previous link for this chat is
              being revoked.
            </div>
          ) : (
          <div className="mt-3 flex items-center gap-2">
            <input
              ref={inputRef}
              readOnly
              value={url ?? ""}
              aria-label="Share link"
              data-testid="share-link-url"
              onFocus={(event) => event.currentTarget.select()}
              className="min-w-0 flex-1 rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 font-mono text-[11px] text-[var(--color-text)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)]"
            />
            <button
              type="button"
              onClick={() => void copy()}
              data-testid="share-link-copy"
              className="inline-flex flex-none items-center gap-1.5 rounded-[10px] bg-[var(--color-text)] px-3 py-2 text-[12px] font-medium text-[var(--color-bg)] hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-bg-card)]"
            >
              {copied ? (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Copied
                </>
              ) : (
                <>
                  <Copy className="h-3.5 w-3.5" />
                  Copy link
                </>
              )}
            </button>
          </div>
          )}

          <div
            data-testid="share-link-privacy"
            className="mt-4 flex gap-3 rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg)] px-3.5 py-3"
          >
            <LockKeyhole className="mt-0.5 h-3.5 w-3.5 flex-none text-[var(--color-success)]" />
            <div className="text-xs leading-relaxed text-[var(--color-text-muted)]">
              <div className="font-medium text-[var(--color-text)]">
                Private to your organization
              </div>
              Only people signed in to your organization can open this link.
              It is not public and never becomes public: anyone else, signed
              in or not, sees nothing. Sharing again replaces this link, and
              you can revoke it at any time from the chat menu.
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end border-t border-[var(--color-border)] px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-[10px] px-4 py-2 text-[12px] text-[var(--color-text-dim)] transition-colors hover:text-[var(--color-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)]"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
