"use client";

// Compact card an assistant message shows when a run created a governed
// dashboard preview. Viewing it opens the chat's dashboard panel.

import { LayoutDashboard } from "lucide-react";
import { useChatUi } from "~/components/chat/chat-ui-context";

export type DashboardPreview = {
  authoring_session_id: string;
  dashboard_name: string;
  summary: string;
  chart_count: number;
};

export function messageDashboardPreview(
  metadata: Record<string, unknown>,
): DashboardPreview | null {
  const value = metadata.dashboard_preview;
  if (!value || typeof value !== "object") return null;
  const preview = value as Record<string, unknown>;
  if (
    typeof preview.authoring_session_id !== "string" ||
    !preview.authoring_session_id ||
    typeof preview.dashboard_name !== "string"
  ) {
    return null;
  }
  return {
    authoring_session_id: String(preview.authoring_session_id || ""),
    dashboard_name: preview.dashboard_name,
    summary: typeof preview.summary === "string" ? preview.summary : "",
    chart_count:
      typeof preview.chart_count === "number" ? preview.chart_count : 0,
  };
}

export function DashboardPreviewCard({
  preview,
}: {
  preview: DashboardPreview;
}) {
  const { onOpenDashboardPreview } = useChatUi();
  const chartLabel = `${preview.chart_count} chart${
    preview.chart_count === 1 ? "" : "s"
  }`;
  return (
    <section
      data-testid="dashboard-artifact-card"
      className="mt-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-3"
    >
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex h-14 w-14 flex-none items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)]">
          <LayoutDashboard className="h-5 w-5 text-[var(--color-text-muted)]" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-[var(--color-text-dim)]">
            Dashboard
          </p>
          <p className="mt-1 truncate text-sm font-medium text-[var(--color-text)]">
            {preview.dashboard_name}
          </p>
          <p className="mt-1 truncate text-xs text-[var(--color-text-dim)]">
            {chartLabel} · Draft ready for review
          </p>
        </div>
        <button
          type="button"
          aria-label={`View ${preview.dashboard_name}`}
          title={preview.summary || `View ${preview.dashboard_name}`}
          onClick={() => onOpenDashboardPreview(preview.authoring_session_id)}
          className="flex-none rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-4 py-2 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)]"
        >
          View
        </button>
      </div>
    </section>
  );
}
