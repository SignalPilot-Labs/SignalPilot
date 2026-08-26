"use client";

import { FileChartColumn, Send, X } from "lucide-react";
import {
  useCallback,
  useMemo,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import useSWR from "swr";
import { getChatReportMentions, type ChatReportMention } from "~/lib/api";

export function StandaloneChatComposer({
  value,
  onValueChange,
  onSubmit,
  submitDisabled,
  placeholder,
  projectPicker,
  projectId,
  selectedReport,
  onSelectedReportChange,
}: {
  value: string;
  onValueChange: (value: string) => void;
  onSubmit: (value: string) => void;
  submitDisabled: boolean;
  placeholder: string;
  projectPicker?: ReactNode;
  projectId?: string | null;
  selectedReport?: ChatReportMention | null;
  onSelectedReportChange?: (report: ChatReportMention | null) => void;
}) {
  const mentionQuery = useMemo(() => {
    if (selectedReport || !projectId) return null;
    const match = /(?:^|\s)@([^@\n]*)$/.exec(value);
    return match ? match[1].trim() : null;
  }, [projectId, selectedReport, value]);
  const { data: mentionData } = useSWR(
    mentionQuery !== null && projectId
      ? ["chat-report-mentions", projectId, mentionQuery]
      : null,
    () => getChatReportMentions(projectId!, mentionQuery || ""),
    { keepPreviousData: true },
  );
  const canSubmit = Boolean(value.trim()) && !submitDisabled;
  const submit = useCallback(() => {
    const text = value.trim();
    if (!text || submitDisabled) return;
    onValueChange("");
    onSubmit(text);
  }, [onSubmit, onValueChange, submitDisabled, value]);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing ||
      !canSubmit
    ) {
      return;
    }
    event.preventDefault();
    submit();
  };

  const selectReport = (report: ChatReportMention) => {
    onValueChange(value.replace(/(?:^|\s)@([^@\n]*)$/, "").trimEnd());
    onSelectedReportChange?.(report);
  };

  return (
    <div
      data-testid="standalone-chat-composer"
      className="mx-auto w-full max-w-3xl px-6 pb-6 pt-3"
    >
      <div className="relative rounded-2xl border border-[var(--color-border-hover)] bg-[var(--color-bg-input)] shadow-2xl shadow-black/20 transition-colors focus-within:border-[var(--color-border-active)]">
        {projectPicker && (
          <div className="flex items-center border-b border-[var(--color-border)] px-4 py-2.5">
            {projectPicker}
          </div>
        )}
        {selectedReport && (
          <div className="flex items-center gap-2 border-b border-[var(--color-border)] px-4 py-2.5 text-xs text-[var(--color-text-muted)]">
            <FileChartColumn className="h-3.5 w-3.5" />
            <span className="min-w-0 flex-1 truncate">
              @{selectedReport.title}
            </span>
            <button
              type="button"
              aria-label={`Remove report ${selectedReport.title}`}
              onClick={() => onSelectedReportChange?.(null)}
              className="rounded p-0.5 text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
        {mentionQuery !== null && (mentionData?.items.length ?? 0) > 0 && (
          <div
            role="listbox"
            aria-label="Saved reports"
            className="absolute bottom-full left-0 z-30 mb-2 max-h-64 w-full overflow-y-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-1 shadow-2xl"
          >
            {mentionData!.items.map((report) => (
              <button
                type="button"
                role="option"
                aria-selected="false"
                key={report.report_id}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => selectReport(report)}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-[var(--color-bg-hover)]"
              >
                <FileChartColumn className="h-3.5 w-3.5 flex-none text-[var(--color-text-dim)]" />
                <span className="min-w-0 flex-1 truncate text-xs text-[var(--color-text)]">
                  {report.title}
                </span>
                <span className="text-[10px] uppercase text-[var(--color-text-dim)]">
                  {report.kind}
                </span>
              </button>
            ))}
          </div>
        )}
        <textarea
          data-chat-composer
          rows={1}
          autoFocus
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="max-h-48 min-h-14 w-full resize-none border-0 bg-transparent px-4 py-4 pr-14 text-sm leading-6 text-[var(--color-text)] shadow-none outline-none placeholder:text-[var(--color-text-dim)] focus:border-0 focus:shadow-none focus:outline-none focus-visible:outline-none focus-visible:ring-0"
        />
        <button
          type="button"
          disabled={!canSubmit}
          onClick={submit}
          aria-label="Send message"
          className="absolute bottom-3 right-3 flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-text)] text-[var(--color-bg)] disabled:cursor-not-allowed disabled:opacity-30"
        >
          <Send className="h-3.5 w-3.5" />
        </button>
      </div>
      <p className="mt-2 text-center text-[10px] text-[var(--color-text-dim)]">
        Answers use governed, read-only access. Check freshness and caveats.
      </p>
    </div>
  );
}
