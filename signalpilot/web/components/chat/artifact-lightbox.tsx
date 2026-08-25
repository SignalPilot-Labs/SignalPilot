"use client";

import { X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * Fullscreen viewer for chat artifacts (chart images, HTML reports, large
 * previews). Rendered through a portal so ancestor overflow/transform
 * containers cannot clip it. Closes on Escape, backdrop click, or the button.
 */
export function ArtifactLightbox({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, onClose]);
  if (!open || !mounted) return null;
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-testid="artifact-lightbox"
      className="fixed inset-0 z-[100] flex flex-col bg-black/80 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex flex-none items-center justify-between gap-4 px-5 py-3"
        onClick={(event) => event.stopPropagation()}
      >
        <span className="truncate font-mono text-sm text-[var(--color-text)]">
          {title}
        </span>
        <button
          type="button"
          aria-label="Close viewer"
          onClick={onClose}
          className="flex h-9 w-9 flex-none items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div
        className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-4 pt-0"
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
