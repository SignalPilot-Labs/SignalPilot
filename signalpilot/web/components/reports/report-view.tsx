"use client";

import { useState } from "react";
import { Loader2, Trash2, Link2, ExternalLink } from "lucide-react";
import type { ReportSummary } from "~/lib/types";
import { useReport, invalidateReports } from "~/lib/hooks/use-gateway-data";
import { deleteReport } from "~/lib/api";
import { useToast } from "~/components/ui/toast";
import { ConfirmDialog } from "~/components/ui/confirm-dialog";
import { EmptyList, EmptyState } from "~/components/ui/empty-states";
import { TimeAgo } from "~/components/ui/time-ago";

/** Build the shareable URL for a report (works in browser only). */
export function reportShareUrl(id: string): string {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return `${origin}/reports?report=${id}`;
}

/** Left-rail list of reports. */
export function ReportList({
  reports,
  selectedId,
  onSelect,
  filterQ,
}: {
  reports: ReportSummary[] | undefined;
  selectedId: string | null;
  onSelect: (id: string) => void;
  filterQ?: string;
}) {
  const q = (filterQ || "").trim().toLowerCase();
  const filtered = (reports || []).filter((r) => !q || r.title.toLowerCase().includes(q));

  if (!reports) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-dim)]" />
      </div>
    );
  }
  if (filtered.length === 0) {
    return (
      <div className="px-4 py-8 text-center text-[12px] text-[var(--color-text-dim)] tracking-wider">
        {q ? "no matches" : "no reports"}
      </div>
    );
  }
  return (
    <div className="py-1">
      {filtered.map((r) => (
        <button
          key={r.id}
          onClick={() => onSelect(r.id)}
          className={`w-full text-left px-3 py-2 border-l-2 transition-colors ${
            selectedId === r.id
              ? "border-[var(--color-text)] bg-[var(--color-bg-hover)]"
              : "border-transparent hover:bg-[var(--color-bg-hover)]"
          }`}
        >
          <div className="text-[12px] text-[var(--color-text)] truncate tracking-wide">{r.title}</div>
          <div className="text-[10px] text-[var(--color-text-dim)] tracking-wider mt-0.5 flex items-center gap-2">
            <TimeAgo timestamp={r.created_at} />
            {r.scope_ref ? <span className="truncate">· {r.scope_ref}</span> : null}
          </div>
        </button>
      ))}
    </div>
  );
}

/** Sandboxed HTML report renderer with a toolbar. */
export function ReportViewer({
  reportId,
  onDeleted,
}: {
  reportId: string | null;
  onDeleted?: () => void;
}) {
  const { toast } = useToast();
  const { data: report, isLoading } = useReport(reportId);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  if (!reportId) {
    return (
      <EmptyState
        icon={EmptyList}
        title="select a report"
        description="choose a report from the list to render it"
      />
    );
  }
  if (isLoading || !report) {
    return (
      <div className="flex items-center justify-center flex-1">
        <Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-dim)]" />
      </div>
    );
  }

  // Open the raw HTML document in a new tab — no app chrome, just the file.
  function openRaw() {
    const blob = new Blob([report!.html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const win = window.open(url, "_blank", "noopener,noreferrer");
    if (!win) toast("popup blocked — allow popups to open the report", "error");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(reportShareUrl(reportId!));
      toast("link copied", "success");
    } catch {
      toast("could not copy link", "error");
    }
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await deleteReport(reportId!);
      await invalidateReports();
      toast("report deleted", "success");
      setConfirmDelete(false);
      onDeleted?.();
    } catch (err) {
      toast(err instanceof Error ? err.message : "delete failed", "error");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="flex flex-col flex-1 min-w-0">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-[var(--color-border)]">
        <div className="min-w-0">
          <div className="text-[13px] text-[var(--color-text)] truncate tracking-wide">{report.title}</div>
          <div className="text-[10px] text-[var(--color-text-dim)] tracking-wider">
            {report.proposed_by_agent ? `by ${report.proposed_by_agent} · ` : ""}
            <TimeAgo timestamp={report.created_at} /> · {report.view_count} views
          </div>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={copyLink}
            title="copy shareable link"
            className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
          >
            <Link2 className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={openRaw}
            title="open raw HTML in new tab"
            className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => setConfirmDelete(true)}
            title="delete permanently"
            className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-error)] transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Sandboxed render — opaque origin (no allow-same-origin) isolates report scripts. */}
      <iframe
        title={report.title}
        srcDoc={report.html}
        sandbox="allow-scripts allow-popups allow-forms"
        className="flex-1 w-full border-0 bg-white"
      />

      <ConfirmDialog
        open={confirmDelete}
        title="delete report"
        message={`Permanently delete "${report.title}"? This cannot be undone.`}
        confirmLabel={deleting ? "deleting..." : "delete"}
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}
