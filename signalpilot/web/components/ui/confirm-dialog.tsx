"use client";

import { useCallback, useEffect, useRef } from "react";

/**
 * Minimal confirmation dialog — terminal-aesthetic.
 * Replaces browser confirm() with an in-app dialog.
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "confirm",
  cancelLabel = "cancel",
  variant = "danger",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "default";
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) confirmRef.current?.focus();
  }, [open]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter") onConfirm();
    },
    [onCancel, onConfirm]
  );

  if (!open) return null;

  const isDanger = variant === "danger";

  return (
    <div
      className="fixed inset-0 z-[100] flex items-end sm:items-center justify-center bg-black/70 px-0 sm:px-4"
      onClick={onCancel}
      onKeyDown={handleKeyDown}
    >
      <div
        className="w-full sm:w-[360px] bg-[var(--color-bg-card)] border border-[var(--color-border)] shadow-2xl animate-scale-in safe-area-bottom"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center gap-2">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
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
          <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
            {title}
          </span>
        </div>

        {/* Body */}
        <div className="px-5 py-4">
          <p className="text-xs text-[var(--color-text-muted)] tracking-wider leading-relaxed">
            {message}
          </p>
        </div>

        {/* Actions */}
        <div className="px-5 py-3 sm:py-3 border-t border-[var(--color-border)] flex flex-col-reverse sm:flex-row items-stretch sm:items-center sm:justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-4 py-3 sm:py-2 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider uppercase text-center"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            onClick={onConfirm}
            className={`px-4 py-3 sm:py-2 text-[10px] font-medium tracking-wider uppercase transition-all text-center ${
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
