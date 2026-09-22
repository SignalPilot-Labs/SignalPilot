"use client";

import { FileImage, Globe, LayoutDashboard, NotebookPen, X } from "lucide-react";
import type { ArtifactNotice, ArtifactNoticeKind } from "~/lib/chat-artifact-notices";

const ICONS: Record<ArtifactNoticeKind, typeof NotebookPen> = {
  notebook: NotebookPen,
  chart: FileImage,
  dashboard: LayoutDashboard,
  report: Globe,
};

/**
 * The stack of artifact notices under the floating panel toggles: one
 * small card per new notebook, chart, dashboard or report, each with a
 * "View" action that opens the artifacts panel on it. Replaces the panel
 * opening by itself, which yanked the transcript narrower mid-read.
 */
export function ArtifactNotices({
  notices,
  onView,
  onDismiss,
}: {
  notices: ArtifactNotice[];
  onView: (notice: ArtifactNotice) => void;
  onDismiss: (id: string) => void;
}) {
  if (notices.length === 0) return null;
  return (
    <div
      data-testid="artifact-notices"
      aria-live="polite"
      className="absolute right-4 top-16 z-20 flex w-72 flex-col gap-2"
    >
      {notices.map((notice) => {
        const Icon = ICONS[notice.kind];
        return (
          <div
            key={notice.id}
            role="status"
            data-testid="artifact-notice"
            data-notice-kind={notice.kind}
            className="chat-boot-in flex items-center gap-2.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] py-2 pl-3 pr-1.5 shadow-lg shadow-black/20"
          >
            <Icon className="h-4 w-4 flex-none text-[var(--color-success)]" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[12px] font-medium text-[var(--color-text)]">
                {notice.title}
              </div>
              {notice.detail && (
                <div className="truncate text-[11px] text-[var(--color-text-dim)]">
                  {notice.detail}
                </div>
              )}
            </div>
            <button
              type="button"
              data-testid="artifact-notice-view"
              onClick={() => onView(notice)}
              className="flex-none rounded-md border border-[var(--color-border)] px-2 py-1 text-[11px] font-medium text-[var(--color-text)] hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)]"
            >
              View
            </button>
            <button
              type="button"
              aria-label="Dismiss"
              data-testid="artifact-notice-dismiss"
              onClick={() => onDismiss(notice.id)}
              className="flex h-6 w-6 flex-none items-center justify-center rounded-md text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
