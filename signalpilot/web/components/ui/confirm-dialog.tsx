"use client";

import React, { useCallback, useEffect, useRef } from "react";
import { useFocusTrap } from "./use-focus-trap";

/**
 * Minimal confirmation dialog — terminal-aesthetic.
 * Replaces browser confirm() with an in-app dialog. Focus is trapped inside
 * while open and returned to the opener on close.
 *
 * `titleCase="sentence"` renders the title as a calm sentence ("Remove Jira
 * for everyone?") instead of the default uppercase eyebrow.
 */
export function ConfirmDialog({
  open,
  title,
  message,
  body,
  confirmLabel = "confirm",
  cancelLabel = "cancel",
  variant = "danger",
  titleCase = "upper",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  body?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "default";
  titleCase?: "upper" | "sentence";
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);
  useFocusTrap(panelRef, open);

  useEffect(() => {
    if (!open) return;
    restoreFocus.current = document.activeElement as HTMLElement | null;
    confirmRef.current?.focus();
    return () => restoreFocus.current?.focus?.();
  }, [open]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCancel();
      }
      if (e.key === "Enter") onConfirm();
    },
    [onCancel, onConfirm]
  );

  if (!open) return null;

  const isDanger = variant === "danger";

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 !ml-0"
      onClick={onCancel}
      onKeyDown={handleKeyDown}
    >
      <div
        ref={panelRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
        data-testid="confirm-dialog"
        className="w-[360px] rounded-[14px] overflow-hidden bg-[var(--color-bg-card)] border border-[var(--color-border)] shadow-2xl animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center gap-2">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="flex-none">
            {isDanger ? (
              <>
                <path d="M7 1L13 13H1L7 1Z" stroke="var(--color-error)" strokeWidth="1" fill="none" />
                <line x1="7" y1="5" x2="7" y2="9" stroke="var(--color-error)" strokeWidth="1.5" strokeLinecap="round" />
                <circle cx="7" cy="11" r="0.75" fill="var(--color-error)" />
              </>
            ) : (
              <>
                <circle cx="7" cy="7" r="6" stroke="var(--color-text-dim)" strokeWidth="1" fill="none" />
                <text x="7" y="10" textAnchor="middle" fill="var(--color-text-dim)" fontSize="8" fontFamily="monospace">?</text>
              </>
            )}
          </svg>
          <span
            id="confirm-dialog-title"
            className={
              titleCase === "sentence"
                ? "text-[13px] font-medium text-[var(--color-text)]"
                : "text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]"
            }
          >
            {title}
          </span>
        </div>

        {/* Body */}
        <div className="px-5 py-4">
          <p id="confirm-dialog-message" className="text-xs text-[var(--color-text-muted)] leading-relaxed">
            {message}
          </p>
          {body ? <div className="mt-3">{body}</div> : null}
        </div>

        {/* Actions */}
        <div className="px-5 py-3 border-t border-[var(--color-border)] flex items-center justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-4 py-2 rounded-[10px] text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)]"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            onClick={onConfirm}
            className={`px-4 py-2 rounded-[10px] text-[12px] font-medium transition-opacity duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-bg-card)] ${
              isDanger
                ? "bg-[var(--color-error)] text-white hover:opacity-90"
                : "bg-[var(--color-text)] text-[var(--color-bg)] hover:opacity-90"
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
