"use client";

// Save-as-report action for chat artifacts.

import { FileChartColumn, Loader2, Save } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { promoteChatArtifact } from "~/lib/api";
import { useToast } from "~/components/ui/toast";
import type { ArtifactPreviewData } from "~/components/chat/chat-artifact-preview";

export function SaveArtifactAsReportAction({
  artifact,
}: {
  artifact: ArtifactPreviewData;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const isUpdate =
    artifact.report_action === "update" && Boolean(artifact.saved_report_id);

  if (artifact.report_action === "open" && artifact.saved_report_id) {
    return (
      <button
        type="button"
        onClick={() => router.push(`/reports/${artifact.saved_report_id}`)}
        className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-text)] px-2 py-1 text-[11px] text-[var(--color-bg)]"
      >
        <FileChartColumn className="h-3 w-3" />
        Open report
      </button>
    );
  }

  const begin = () => {
    setTitle(
      isUpdate && artifact.saved_report_title
        ? artifact.saved_report_title
        : artifact.filename.replace(/\.[^.]+$/, ""),
    );
    setOpen(true);
  };

  const submit = async () => {
    const cleanTitle = title.trim();
    if (!cleanTitle || submitting) return;
    setSubmitting(true);
    try {
      const result = await promoteChatArtifact(artifact.id, cleanTitle);
      setOpen(false);
      toast(
        result.status === "created"
          ? "Report saved"
          : result.status === "updated"
            ? "Report updated"
            : "Report already up to date",
        "success",
      );
      router.push(`/reports/${result.report_id}`);
    } catch (error) {
      toast(
        error instanceof Error
          ? error.message
          : isUpdate
            ? "Could not update report"
            : "Could not save report",
        "error",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={begin}
        className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-text)] px-2 py-1 text-[11px] text-[var(--color-bg)]"
      >
        <Save className="h-3 w-3" />
        {isUpdate ? "Update report" : "Save as report"}
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={`save-report-title-${artifact.id}`}
            className="w-full max-w-md rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-5 text-left shadow-2xl"
          >
            <h2
              id={`save-report-title-${artifact.id}`}
              className="text-base text-[var(--color-text)]"
            >
              {isUpdate ? "Update report" : "Save as report"}
            </h2>
            <p className="mt-1 text-xs text-[var(--color-text-dim)]">
              {isUpdate
                ? `This artifact will become a new version of “${title}”.`
                : "Save this artifact as a report you can refresh and share later."}
            </p>
            {!isUpdate && (
              <label className="mt-4 block text-xs text-[var(--color-text-muted)]">
                Report title
                <input
                  autoFocus
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void submit();
                  }}
                  className="mt-2 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-border-hover)]"
                />
              </label>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                disabled={submitting}
                onClick={() => setOpen(false)}
                className="rounded-xl px-3 py-2 text-xs text-[var(--color-text-muted)] disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={!title.trim() || submitting}
                onClick={() => void submit()}
                className="inline-flex items-center gap-2 rounded-xl bg-[var(--color-text)] px-3 py-2 text-xs text-[var(--color-bg)] disabled:opacity-50"
              >
                {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {isUpdate ? "Update report" : "Save report"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
