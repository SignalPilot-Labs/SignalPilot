"use client";

import {
  CalendarDays,
  ArrowDownToLine,
  ArrowLeft,
  AlertTriangle,
  BarChart3,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Clock3,
  FileText,
  History as HistoryIcon,
  Loader2,
  MessageSquare,
  RefreshCw,
  Save,
  Search,
  Share2,
  SlidersHorizontal,
  Table2,
  X,
} from "lucide-react";
import { parseDate } from "@internationalized/date";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useDeferredValue, useEffect, useMemo, useState } from "react";
import {
  Button as AriaButton,
  CalendarCell as AriaCalendarCell,
  CalendarGrid as AriaCalendarGrid,
  CalendarGridBody as AriaCalendarGridBody,
  CalendarGridHeader as AriaCalendarGridHeader,
  CalendarHeaderCell as AriaCalendarHeaderCell,
  DateInput as AriaDateInput,
  DateRangePicker as AriaDateRangePicker,
  DateSegment as AriaDateSegment,
  Dialog as AriaDialog,
  Group as AriaGroup,
  Heading as AriaHeading,
  Popover as AriaPopover,
  RangeCalendar as AriaRangeCalendar,
} from "react-aria-components";
import { VegaEmbed } from "react-vega";
import useSWR from "swr";
import type { VisualizationSpec } from "vega-embed";
import {
  downloadSavedReportVersion,
  downloadStandaloneArtifact,
  getChatLibrary,
  getSavedChatReport,
  getSavedReportVersionObjectUrl,
  getSharedSavedChatReport,
  getStandaloneChatBootstrap,
  getStandaloneArtifactObjectUrl,
  promoteChatArtifact,
  publishSavedChatReportVersion,
  refreshSavedChatReport,
  revokeSavedChatReportVersionShare,
  shareSavedChatReportVersion,
  type ChatLibraryArtifact,
  type ChatLibraryFilters,
  type ChatLibraryReport,
  type ChatReportFreshness,
  type SavedReportDetail,
  type SavedReportVersion,
} from "~/lib/api";
import { PageHeader } from "~/components/ui/page-header";
import { useToast } from "~/components/ui/toast";

function freshnessLabel(state: ChatReportFreshness, at: string | null) {
  if (state === "changes_detected") return "Changes detected";
  if (state === "fresh" && at)
    return `Fresh through ${new Date(at).toLocaleString()}`;
  return "Unknown";
}

function freshnessTone(state: ChatReportFreshness) {
  if (state === "changes_detected")
    return "border-[var(--color-warning)]/30 text-[var(--color-warning)]";
  if (state === "fresh")
    return "border-[var(--color-success)]/30 text-[var(--color-success)]";
  return "border-[var(--color-border)] text-[var(--color-text-dim)]";
}

function refreshLabel(
  status: NonNullable<SavedReportDetail["refresh"]>["status"],
) {
  return {
    refreshing: "Refreshing",
    update_available: "Update available",
    failed: "Failed",
    current: "Current",
  }[status];
}

function KindIcon({ kind }: { kind: "table" | "chart" | "report" }) {
  if (kind === "table") return <Table2 className="h-4 w-4" />;
  if (kind === "chart") return <BarChart3 className="h-4 w-4" />;
  return <FileText className="h-4 w-4" />;
}

function PreviewError() {
  return (
    <div
      role="alert"
      className="flex min-h-64 flex-col items-center justify-center rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-bg-card)] px-6 text-center"
    >
      <AlertTriangle className="h-5 w-5 text-[var(--color-error)]" />
      <p className="mt-3 text-sm text-[var(--color-text)]">
        Preview unavailable
      </p>
      <p className="mt-1 max-w-md text-xs leading-5 text-[var(--color-text-dim)]">
        Something unexpected happened while loading this preview. You can still
        download the file.
      </p>
    </div>
  );
}

function RuntimeChartPreview({
  artifactId,
  versionId,
  filename,
}: {
  artifactId?: string;
  versionId?: string;
  filename: string;
}) {
  const [state, setState] = useState<{
    url: string | null;
    error: boolean;
  }>({ url: null, error: false });

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setState({ url: null, error: false });
    const pending = artifactId
      ? getStandaloneArtifactObjectUrl(artifactId, "png")
      : versionId
        ? getSavedReportVersionObjectUrl(versionId, "png")
        : Promise.reject(new Error("Chart preview source is unavailable"));
    void pending
      .then((url) => {
        objectUrl = url;
        if (active) setState({ url, error: false });
      })
      .catch(() => {
        if (active) setState({ url: null, error: true });
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [artifactId, versionId]);

  if (state.error) return <PreviewError />;
  if (!state.url) {
    return (
      <div className="flex min-h-64 items-center justify-center rounded-xl border border-[var(--color-border)] text-xs text-[var(--color-text-dim)]">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading preview…
      </div>
    );
  }
  return (
    <div className="flex min-h-full items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
      <img src={state.url} alt={filename} className="max-h-full max-w-full" />
    </div>
  );
}

function VegaChartPreview({ spec }: { spec: VisualizationSpec }) {
  const [hasError, setHasError] = useState(false);
  if (hasError) return <PreviewError />;
  return (
    <div className="mx-auto w-fit min-w-[640px]">
      <VegaEmbed
        spec={spec}
        options={{ actions: false, mode: "vega-lite", renderer: "svg" }}
        onError={() => setHasError(true)}
      />
    </div>
  );
}

function ReportContentPreview({
  kind,
  snapshot,
  filename,
  fill = false,
  artifactId,
  versionId,
}: {
  kind: "table" | "chart" | "report";
  snapshot: Record<string, unknown>;
  filename: string;
  fill?: boolean;
  artifactId?: string;
  versionId?: string;
}) {
  if (kind === "table") {
    const columns = Array.isArray(snapshot.columns)
      ? snapshot.columns
          .map((column) =>
            typeof column === "string"
              ? column
              : typeof column === "object" && column && "name" in column
                ? String(column.name)
                : "",
          )
          .filter(Boolean)
      : [];
    const rows = Array.isArray(snapshot.rows)
      ? snapshot.rows.filter(
          (row): row is Record<string, unknown> =>
            typeof row === "object" && row !== null,
        )
      : [];
    return (
      <div
        className={`${fill ? "h-full" : "max-h-80"} overflow-auto rounded-xl border border-[var(--color-border)]`}
      >
        <table className="w-full border-collapse text-left text-xs">
          <thead className="sticky top-0 bg-[var(--color-bg-elevated)]">
            <tr>
              {columns.map((column) => (
                <th
                  key={column}
                  className="border-b border-[var(--color-border)] px-3 py-2 font-medium text-[var(--color-text-muted)]"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 20).map((row, index) => (
              <tr
                key={index}
                className="border-b border-[var(--color-border)]/60"
              >
                {columns.map((column) => (
                  <td
                    key={column}
                    className="max-w-64 truncate px-3 py-2 font-mono text-[11px] text-[var(--color-text-muted)]"
                  >
                    {row[column] == null ? "—" : String(row[column])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (kind === "chart") {
    if (snapshot.runtime_png === true) {
      return (
        <RuntimeChartPreview
          artifactId={artifactId}
          versionId={versionId}
          filename={filename}
        />
      );
    }
    const rows = Array.isArray(snapshot.rows) ? snapshot.rows : [];
    const baseSpec =
      typeof snapshot.spec === "object" && snapshot.spec ? snapshot.spec : {};
    const isRenderableSpec = [
      "mark",
      "layer",
      "hconcat",
      "vconcat",
      "concat",
      "facet",
      "repeat",
    ].some((key) => key in baseSpec);
    if (!isRenderableSpec) return <PreviewError />;
    const spec = {
      ...baseSpec,
      data: { values: rows },
      width: 640,
      height: 360,
      autosize: { type: "fit", contains: "padding", resize: true },
    } as VisualizationSpec;
    return (
      <div
        className={`${fill ? "min-h-full" : ""} overflow-x-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4`}
      >
        <VegaChartPreview
          key={artifactId || versionId || filename}
          spec={spec}
        />
      </div>
    );
  }
  const html = typeof snapshot.html === "string" ? snapshot.html : "";
  return (
    <iframe
      title={filename}
      sandbox=""
      referrerPolicy="no-referrer"
      srcDoc={html}
      className={`${fill ? "h-full min-h-[520px]" : "h-[520px]"} w-full rounded-xl border border-[var(--color-border)] bg-white`}
    />
  );
}

function CreatedDateRangeFilter({
  filters,
  setFilters,
}: {
  filters: ChatLibraryFilters;
  setFilters: (value: ChatLibraryFilters) => void;
}) {
  const value =
    filters.created_from && filters.created_to
      ? {
          start: parseDate(filters.created_from.slice(0, 10)),
          end: parseDate(filters.created_to.slice(0, 10)),
        }
      : null;

  return (
    <AriaDateRangePicker
      aria-label="Created date range"
      value={value}
      onChange={(range) =>
        setFilters({
          ...filters,
          created_from: range
            ? `${range.start.toString()}T00:00:00Z`
            : undefined,
          created_to: range ? `${range.end.toString()}T23:59:59Z` : undefined,
          artifact_cursor: undefined,
          report_cursor: undefined,
        })
      }
      className="min-w-0"
    >
      <AriaGroup className="flex w-full min-w-0 items-center overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-xs text-[var(--color-text-muted)] data-[focus-within]:border-[var(--color-border-hover)]">
        <AriaDateInput slot="start" className="flex min-w-0 items-center">
          {(segment) => (
            <AriaDateSegment
              segment={segment}
              className="rounded px-0.5 outline-none data-[focused]:bg-[var(--color-bg-hover)] data-[focused]:text-[var(--color-text)] data-[placeholder]:text-[var(--color-text-dim)]"
            />
          )}
        </AriaDateInput>
        <span aria-hidden="true" className="px-1 text-[var(--color-text-dim)]">
          –
        </span>
        <AriaDateInput slot="end" className="flex min-w-0 flex-1 items-center">
          {(segment) => (
            <AriaDateSegment
              segment={segment}
              className="rounded px-0.5 outline-none data-[focused]:bg-[var(--color-bg-hover)] data-[focused]:text-[var(--color-text)] data-[placeholder]:text-[var(--color-text-dim)]"
            />
          )}
        </AriaDateInput>
        <AriaButton
          aria-label="Open date range calendar"
          className="ml-2 flex-none rounded p-1 text-white outline-none hover:bg-[var(--color-bg-hover)]"
        >
          <CalendarDays className="h-4 w-4 text-white" />
        </AriaButton>
      </AriaGroup>
      <AriaPopover
        placement="bottom start"
        className="z-[100] rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-3 text-[var(--color-text)] shadow-2xl outline-none"
      >
        <AriaDialog className="outline-none">
          <AriaRangeCalendar className="w-fit outline-none">
            <header className="mb-3 flex items-center gap-2">
              <AriaButton
                slot="previous"
                aria-label="Previous month"
                className="rounded-lg border border-[var(--color-border)] p-1.5 text-white hover:bg-[var(--color-bg-hover)]"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </AriaButton>
              <AriaHeading className="flex-1 text-center text-xs font-medium" />
              <AriaButton
                slot="next"
                aria-label="Next month"
                className="rounded-lg border border-[var(--color-border)] p-1.5 text-white hover:bg-[var(--color-bg-hover)]"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </AriaButton>
            </header>
            <AriaCalendarGrid className="border-separate border-spacing-1">
              <AriaCalendarGridHeader>
                {(day) => (
                  <AriaCalendarHeaderCell className="h-7 w-7 text-center text-[10px] font-normal text-[var(--color-text-dim)]">
                    {day}
                  </AriaCalendarHeaderCell>
                )}
              </AriaCalendarGridHeader>
              <AriaCalendarGridBody>
                {(date) => (
                  <AriaCalendarCell
                    date={date}
                    className={({
                      isDisabled,
                      isFocused,
                      isOutsideMonth,
                      isSelected,
                      isSelectionEnd,
                      isSelectionStart,
                    }) =>
                      `flex h-7 w-7 items-center justify-center rounded-md text-[11px] outline-none ${
                        isDisabled || isOutsideMonth
                          ? "text-[var(--color-text-dim)] opacity-40"
                          : "text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)]"
                      } ${isSelected ? "bg-white/15 text-white" : ""} ${
                        isSelectionStart || isSelectionEnd
                          ? "bg-white text-[var(--color-bg)]"
                          : ""
                      } ${isFocused ? "ring-1 ring-white" : ""}`
                    }
                  />
                )}
              </AriaCalendarGridBody>
            </AriaCalendarGrid>
          </AriaRangeCalendar>
        </AriaDialog>
      </AriaPopover>
    </AriaDateRangePicker>
  );
}

function Filters({
  filters,
  setFilters,
  facets,
}: {
  filters: ChatLibraryFilters;
  setFilters: (value: ChatLibraryFilters) => void;
  facets?: {
    artifact_types: string[];
    projects: Array<{ id: string; name: string }>;
    original_threads: Array<{ id: string; title: string }>;
  };
}) {
  const set = (name: keyof ChatLibraryFilters, value: string) =>
    setFilters({
      ...filters,
      [name]: value || undefined,
      artifact_cursor: undefined,
      report_cursor: undefined,
    });
  return (
    <div className="grid min-w-0 gap-2 border-t border-[var(--color-border)] bg-[var(--color-bg-card)] p-3">
      <select
        aria-label="Artifact type"
        value={filters.kind || ""}
        onChange={(event) => set("kind", event.target.value)}
        className="w-full min-w-0 max-w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-xs text-[var(--color-text-muted)]"
      >
        <option value="">All types</option>
        {(facets?.artifact_types || []).map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
      <select
        aria-label="Project"
        value={filters.project_id || ""}
        onChange={(event) => set("project_id", event.target.value)}
        className="w-full min-w-0 max-w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-xs text-[var(--color-text-muted)]"
      >
        <option value="">All projects</option>
        {(facets?.projects || []).map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
      <select
        aria-label="Original thread"
        value={filters.original_thread_id || ""}
        onChange={(event) => set("original_thread_id", event.target.value)}
        className="w-full min-w-0 max-w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-xs text-[var(--color-text-muted)]"
      >
        <option value="">All threads</option>
        {(facets?.original_threads || []).map((thread) => (
          <option key={thread.id} value={thread.id}>
            {thread.title}
          </option>
        ))}
      </select>
      <select
        aria-label="Freshness"
        value={filters.freshness || ""}
        onChange={(event) => set("freshness", event.target.value)}
        className="w-full min-w-0 max-w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-xs text-[var(--color-text-muted)]"
      >
        <option value="">Any freshness</option>
        <option value="fresh">Fresh</option>
        <option value="changes_detected">Changes detected</option>
        <option value="unknown">Unknown</option>
      </select>
      <select
        aria-label="Saved state"
        value={filters.saved || ""}
        onChange={(event) => set("saved", event.target.value)}
        className="w-full min-w-0 max-w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-xs text-[var(--color-text-muted)]"
      >
        <option value="">Saved and unsaved</option>
        <option value="saved">Saved</option>
        <option value="unsaved">Unsaved</option>
      </select>
      <CreatedDateRangeFilter filters={filters} setFilters={setFilters} />
    </div>
  );
}

function ArtifactListItem({
  artifact,
  selected,
  onSelect,
}: {
  artifact: ChatLibraryArtifact;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      className={`w-full border-l-2 px-4 py-3 text-left transition-colors ${
        selected
          ? "border-[var(--color-text)] bg-[var(--color-bg-hover)]"
          : "border-transparent hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <div>
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm text-[var(--color-text)]">
            <KindIcon kind={artifact.kind} />
            <span className="truncate">{artifact.filename}</span>
          </div>
          <p className="mt-1 truncate text-xs text-[var(--color-text-dim)]">
            {artifact.project_name || "No project"} ·{" "}
            {artifact.original_thread_title}
          </p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-[10px]">
        {artifact.freshness_state !== "unknown" && (
          <span
            className={`rounded-full border px-2 py-1 ${freshnessTone(artifact.freshness_state)}`}
          >
            {freshnessLabel(artifact.freshness_state, artifact.freshness_at)}
          </span>
        )}
        <span className="rounded-full border border-[var(--color-border)] px-2 py-1 text-[var(--color-text-dim)]">
          {new Date(artifact.created_at).toLocaleDateString()}
        </span>
      </div>
    </button>
  );
}

function ReportListItem({
  report,
  selected,
  onSelect,
}: {
  report: ChatLibraryReport;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      className={`w-full border-l-2 px-4 py-3 text-left transition-colors ${
        selected
          ? "border-[var(--color-text)] bg-[var(--color-bg-hover)]"
          : "border-transparent hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm text-[var(--color-text)]">
            <KindIcon kind={report.kind} />
            <span className="truncate">{report.title}</span>
          </div>
          <p className="mt-1 truncate text-xs text-[var(--color-text-dim)]">
            {report.is_shared
              ? "Shared with you · fixed version"
              : `${report.project_name || "No project"} · ${report.original_thread_title}`}
          </p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-[10px]">
        {report.freshness_state !== "unknown" && (
          <span
            className={`rounded-full border px-2 py-1 ${freshnessTone(report.freshness_state)}`}
          >
            {freshnessLabel(report.freshness_state, report.freshness_at)}
          </span>
        )}
        <span className="rounded-full border border-[var(--color-border)] px-2 py-1 text-[var(--color-text-dim)]">
          {new Date(report.updated_at).toLocaleDateString()}
        </span>
      </div>
    </button>
  );
}

type LibrarySelection =
  { tab: "reports"; id: string } | { tab: "artifacts"; id: string };

function LibraryPreview({
  artifact,
  report,
  onSave,
}: {
  artifact?: ChatLibraryArtifact;
  report?: ChatLibraryReport;
  onSave: (artifact: ChatLibraryArtifact) => void;
}) {
  const [displayedArtifactId, setDisplayedArtifactId] = useState<string | null>(
    null,
  );
  useEffect(() => {
    setDisplayedArtifactId(artifact?.id || null);
  }, [artifact?.id]);
  const artifactHistory = artifact?.history?.length
    ? artifact.history
    : artifact
      ? [artifact]
      : [];
  const displayedArtifact = artifact
    ? artifactHistory.find((entry) => entry.id === displayedArtifactId) ||
      artifact
    : undefined;
  const item = displayedArtifact || report;
  if (!item) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-center text-sm text-[var(--color-text-dim)]">
        Select an item from the list to preview it.
      </div>
    );
  }

  const title = displayedArtifact?.filename || report?.title || "Report";
  const originalThreadId =
    artifact?.original_thread_id || report?.original_thread_id;
  const reportId = displayedArtifact?.saved_report_id || report?.report_id;
  const reportDownloadFormat = report
    ? report.kind === "table"
      ? "csv"
      : report.kind === "chart"
        ? "png"
        : "html"
    : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--color-border)] px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm text-[var(--color-text)]">
            <KindIcon kind={item.kind} />
            <span className="truncate">{title}</span>
          </div>
          <p className="mt-1 truncate text-[11px] text-[var(--color-text-dim)]">
            {report?.is_shared
              ? `Shared fixed version · v${report.version_ordinal}`
              : `${artifact?.project_name || report?.project_name || "No project"} · ${artifact?.original_thread_title || report?.original_thread_title}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {artifact && artifactHistory.length > 1 && (
            <div className="group/history relative">
              <button
                type="button"
                aria-haspopup="dialog"
                className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
              >
                <HistoryIcon className="h-3.5 w-3.5" />
                History {artifactHistory.length}
              </button>
              <div
                role="dialog"
                aria-label="Artifact history"
                className="invisible absolute right-0 top-full z-30 mt-2 w-72 translate-y-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-2 opacity-0 shadow-2xl transition group-focus-within/history:visible group-focus-within/history:translate-y-0 group-focus-within/history:opacity-100 group-hover/history:visible group-hover/history:translate-y-0 group-hover/history:opacity-100"
              >
                <p className="px-2 pb-2 pt-1 text-[11px] text-[var(--color-text-dim)]">
                  Artifact history · newest first
                </p>
                <div className="max-h-72 space-y-1 overflow-y-auto">
                  {artifactHistory.map((entry, index) => {
                    const isShowing = entry.id === displayedArtifact?.id;
                    return (
                      <button
                        type="button"
                        key={entry.id}
                        onClick={() => setDisplayedArtifactId(entry.id)}
                        aria-label={`Show ${entry.filename} from ${new Date(entry.created_at).toLocaleString()}`}
                        aria-current={isShowing ? "true" : undefined}
                        className={`w-full rounded-lg px-2.5 py-2 text-left ${
                          isShowing
                            ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                            : "text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)]"
                        }`}
                      >
                        <span className="flex items-center justify-between gap-3 text-xs">
                          <span>
                            {new Date(entry.created_at).toLocaleString()}
                          </span>
                          <span className="text-[10px] text-[var(--color-text-dim)]">
                            {isShowing
                              ? "Showing"
                              : index === 0
                                ? "Latest"
                                : ""}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
          {originalThreadId && (
            <Link
              href={`/chats/${originalThreadId}`}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              Original thread
            </Link>
          )}
          {displayedArtifact?.download_formats.map((format) => (
            <button
              type="button"
              key={format}
              onClick={() =>
                void downloadStandaloneArtifact(
                  displayedArtifact.id,
                  format,
                  displayedArtifact.filename,
                )
              }
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--color-border)] px-3 py-2 text-xs uppercase text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
              aria-label={`Download ${format.toUpperCase()}`}
            >
              <ArrowDownToLine className="h-3.5 w-3.5" />
              {format}
            </button>
          ))}
          {report && reportDownloadFormat && (
            <button
              type="button"
              onClick={() =>
                void downloadSavedReportVersion(
                  report.version_id,
                  reportDownloadFormat,
                  report.filename,
                )
              }
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            >
              <ArrowDownToLine className="h-3.5 w-3.5" />
              Download
            </button>
          )}
          {artifact &&
            displayedArtifact &&
            !displayedArtifact.saved_report_id && (
              <button
                type="button"
                onClick={() =>
                  onSave({
                    ...artifact,
                    ...displayedArtifact,
                  })
                }
                className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--color-text)] px-3 py-2 text-xs text-[var(--color-bg)]"
              >
                <Save className="h-3.5 w-3.5" />
                Save as report
              </button>
            )}
          {reportId && (
            <Link
              href={`/reports/${reportId}`}
              className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--color-text)] px-3 py-2 text-xs text-[var(--color-bg)]"
            >
              <FileText className="h-3.5 w-3.5" />
              Open report
            </Link>
          )}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">
        <ReportContentPreview
          kind={item.kind}
          snapshot={item.snapshot}
          filename={item.filename}
          fill
          artifactId={displayedArtifact?.id}
          versionId={report?.version_id}
        />
      </div>
    </div>
  );
}

export function ChatReportLibrary() {
  const router = useRouter();
  const { toast } = useToast();
  const [filters, setFilters] = useState<ChatLibraryFilters>({ limit: "30" });
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"reports" | "artifacts">(
    "reports",
  );
  const [selected, setSelected] = useState<LibrarySelection | null>(null);
  const deferredSearch = useDeferredValue(filters.search);
  const requestFilters = useMemo(
    () => ({ ...filters, search: deferredSearch }),
    [filters, deferredSearch],
  );
  const queryKey = useMemo(
    () => `chat-report-library:${JSON.stringify(requestFilters)}`,
    [requestFilters],
  );
  const { data, error, isLoading, mutate } = useSWR(queryKey, () =>
    getChatLibrary(requestFilters),
  );
  const [saving, setSaving] = useState<ChatLibraryArtifact | null>(null);
  const [title, setTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const reports = data?.reports.items || [];
  const artifacts = data?.artifacts.items || [];
  const selectedReport =
    selected?.tab === "reports"
      ? reports.find((report) => report.id === selected.id)
      : undefined;
  const selectedArtifact =
    selected?.tab === "artifacts"
      ? artifacts.find((artifact) => artifact.id === selected.id)
      : undefined;
  const activeFilterCount = [
    filters.kind,
    filters.project_id,
    filters.original_thread_id,
    filters.created_from,
    filters.created_to,
    filters.freshness,
    filters.saved,
  ].filter(Boolean).length;

  useEffect(() => {
    if (!data) return;
    const items =
      activeTab === "reports" ? data.reports.items : data.artifacts.items;
    setSelected((current) => {
      if (
        current?.tab === activeTab &&
        items.some((item) => item.id === current.id)
      ) {
        return current;
      }
      return items[0] ? { tab: activeTab, id: items[0].id } : null;
    });
  }, [activeTab, data]);

  async function submitPromotion() {
    if (!saving || !title.trim()) return;
    setSubmitting(true);
    try {
      const result = await promoteChatArtifact(saving.id, title.trim());
      toast(
        result.status === "created"
          ? "Report saved"
          : result.status === "updated"
            ? "Report updated"
            : "Existing report opened",
        "success",
      );
      await mutate();
      router.push(`/reports/${result.report_id}`);
    } catch (promotionError) {
      toast(
        promotionError instanceof Error
          ? promotionError.message
          : "Could not save report",
        "error",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden p-5 md:p-8">
      <PageHeader
        title="reports"
        subtitle="data chat"
        description="Private artifacts and immutable reports from your Data Chat threads"
      />
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)] md:flex-row">
        <aside className="flex max-h-[45%] min-h-0 min-w-0 w-full flex-col overflow-hidden border-b border-[var(--color-border)] md:max-h-none md:w-80 md:flex-none md:border-b-0 md:border-r">
          <div
            role="tablist"
            aria-label="Report library sections"
            className="grid grid-cols-2 border-b border-[var(--color-border)] p-1.5"
          >
            {(
              [
                ["reports", "Reports", reports.length],
                ["artifacts", "Artifacts", artifacts.length],
              ] as const
            ).map(([tab, label, count]) => {
              const isActive = activeTab === tab;
              return (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  onClick={() => setActiveTab(tab)}
                  className={`rounded-lg px-3 py-2 text-xs transition-colors ${
                    isActive
                      ? "bg-[var(--color-bg-elevated)] text-[var(--color-text)]"
                      : "text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
                  }`}
                >
                  {label}
                  <span className="ml-1.5 text-[10px] opacity-70">{count}</span>
                </button>
              );
            })}
          </div>

          <div className="p-3">
            <div className="relative block">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-[var(--color-text-dim)]" />
              <input
                aria-label="Search artifacts and reports"
                value={filters.search || ""}
                onChange={(event) =>
                  setFilters({
                    ...filters,
                    search: event.target.value || undefined,
                    artifact_cursor: undefined,
                    report_cursor: undefined,
                  })
                }
                placeholder="Search reports…"
                className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg)] py-2 pl-9 pr-8 text-xs text-[var(--color-text)] outline-none focus:border-[var(--color-border-hover)]"
              />
              {filters.search && (
                <button
                  type="button"
                  onClick={() =>
                    setFilters({
                      ...filters,
                      search: undefined,
                      artifact_cursor: undefined,
                      report_cursor: undefined,
                    })
                  }
                  className="absolute right-2 top-2 p-1 text-[var(--color-text-dim)]"
                  aria-label="Clear search"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
            <div className="mt-2 flex min-w-0 items-center gap-1">
              <button
                type="button"
                aria-expanded={filtersOpen}
                aria-controls="report-library-filters"
                onClick={() => setFiltersOpen((open) => !open)}
                className="flex min-w-0 flex-1 items-center justify-between rounded-lg px-2 py-1.5 text-xs text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
              >
                <span className="inline-flex min-w-0 items-center gap-1.5">
                  <SlidersHorizontal className="h-3.5 w-3.5 flex-none" />
                  {filtersOpen ? "Hide filters" : "Show filters"}
                  {activeFilterCount > 0 && (
                    <span className="rounded-full bg-[var(--color-bg-elevated)] px-1.5 py-0.5 text-[10px] text-[var(--color-text-muted)]">
                      {activeFilterCount}
                    </span>
                  )}
                </span>
                {filtersOpen ? (
                  <ChevronUp className="h-3.5 w-3.5 flex-none" />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5 flex-none" />
                )}
              </button>
              {activeFilterCount > 0 && (
                <button
                  type="button"
                  onClick={() =>
                    setFilters({
                      limit: filters.limit || "30",
                      search: filters.search,
                    })
                  }
                  className="flex-none rounded-lg px-2 py-1.5 text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                >
                  Clear filters
                </button>
              )}
            </div>
          </div>

          {filtersOpen && (
            <div
              id="report-library-filters"
              className="max-h-72 min-w-0 overflow-x-hidden overflow-y-auto"
            >
              <Filters
                filters={filters}
                setFilters={setFilters}
                facets={data?.facets}
              />
            </div>
          )}

          <div className="min-h-0 flex-1 overflow-y-auto border-t border-[var(--color-border)]">
            {error ? (
              <div className="p-5 text-center text-xs text-[var(--color-error)]">
                Could not load the report library.
              </div>
            ) : isLoading && !data ? (
              <div className="flex h-32 items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
              </div>
            ) : activeTab === "reports" ? (
              reports.length ? (
                <>
                  {reports.map((report) => (
                    <ReportListItem
                      key={report.id}
                      report={report}
                      selected={
                        selected?.tab === "reports" && selected.id === report.id
                      }
                      onSelect={() =>
                        setSelected({ tab: "reports", id: report.id })
                      }
                    />
                  ))}
                  {data?.reports.next_cursor && (
                    <button
                      type="button"
                      onClick={() =>
                        setFilters({
                          ...filters,
                          report_cursor: data.reports.next_cursor || undefined,
                        })
                      }
                      className="m-3 rounded-xl border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text-muted)]"
                    >
                      Next reports
                    </button>
                  )}
                </>
              ) : (
                <div className="p-8 text-center text-xs text-[var(--color-text-dim)]">
                  No saved reports match these filters.
                </div>
              )
            ) : artifacts.length ? (
              <>
                {artifacts.map((artifact) => (
                  <ArtifactListItem
                    key={artifact.id}
                    artifact={artifact}
                    selected={
                      selected?.tab === "artifacts" &&
                      selected.id === artifact.id
                    }
                    onSelect={() =>
                      setSelected({ tab: "artifacts", id: artifact.id })
                    }
                  />
                ))}
                {data?.artifacts.next_cursor && (
                  <button
                    type="button"
                    onClick={() =>
                      setFilters({
                        ...filters,
                        artifact_cursor:
                          data.artifacts.next_cursor || undefined,
                      })
                    }
                    className="m-3 rounded-xl border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text-muted)]"
                  >
                    Next artifacts
                  </button>
                )}
              </>
            ) : (
              <div className="p-8 text-center text-xs text-[var(--color-text-dim)]">
                No artifacts match these filters.
              </div>
            )}
          </div>
        </aside>

        <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-[var(--color-bg)]">
          <LibraryPreview
            artifact={selectedArtifact}
            report={selectedReport}
            onSave={(value) => {
              setSaving(value);
              setTitle(value.filename.replace(/\.[^.]+$/, ""));
            }}
          />
        </section>
      </div>
      {saving && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-5 shadow-2xl">
            <h2 className="text-base text-[var(--color-text)]">
              Save as report
            </h2>
            <p className="mt-1 text-xs text-[var(--color-text-dim)]">
              Content and artifact type stay immutable. You can publish
              refreshes as new versions later.
            </p>
            <label className="mt-4 block text-xs text-[var(--color-text-muted)]">
              Report title
              <input
                autoFocus
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void submitPromotion();
                }}
                className="mt-2 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-border-hover)]"
              />
            </label>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setSaving(null)}
                className="rounded-xl px-3 py-2 text-xs text-[var(--color-text-muted)]"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={!title.trim() || submitting}
                onClick={() => void submitPromotion()}
                className="inline-flex items-center gap-2 rounded-xl bg-[var(--color-text)] px-3 py-2 text-xs text-[var(--color-bg)] disabled:opacity-50"
              >
                {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Save report
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function VersionDownload({
  version,
}: {
  version: Pick<SavedReportVersion, "id" | "kind" | "filename">;
}) {
  const format =
    version.kind === "table"
      ? "csv"
      : version.kind === "chart"
        ? "png"
        : "html";
  return (
    <button
      type="button"
      onClick={() =>
        void downloadSavedReportVersion(version.id, format, version.filename)
      }
      className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
    >
      <ArrowDownToLine className="h-3.5 w-3.5" />
      Download {format.toUpperCase()}
    </button>
  );
}

export function SavedChatReportDetail({ reportId }: { reportId: string }) {
  const router = useRouter();
  const { toast } = useToast();
  const { data, error, isLoading, mutate } = useSWR(
    `saved-chat-report:${reportId}`,
    () => getSavedChatReport(reportId),
    { refreshInterval: 10_000 },
  );
  const { data: bootstrap } = useSWR(
    "standalone-chat-bootstrap",
    getStandaloneChatBootstrap,
    { revalidateOnFocus: false },
  );
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [shareLink, setShareLink] = useState<{
    versionId: string;
    url: string;
  } | null>(null);

  useEffect(() => {
    if (data && !selectedVersionId)
      setSelectedVersionId(data.current_version_id);
  }, [data, selectedVersionId]);
  const selectedVersion =
    data?.versions.find((version) => version.id === selectedVersionId) ||
    data?.current_version;

  async function beginRefresh() {
    if (!data) return;
    setBusy(true);
    try {
      const refresh = await refreshSavedChatReport(data.id);
      await mutate();
      router.push(`/chats/${refresh.conversation_id}`);
    } catch (refreshError) {
      toast(
        refreshError instanceof Error
          ? refreshError.message
          : "Could not refresh report",
        "error",
      );
    } finally {
      setBusy(false);
    }
  }

  async function publishCandidate(artifactId: string) {
    if (!data) return;
    setBusy(true);
    try {
      await publishSavedChatReportVersion(
        data.id,
        artifactId,
        data.current_version_id,
      );
      toast("Report version updated", "success");
      await mutate();
    } catch (publishError) {
      toast(
        publishError instanceof Error
          ? publishError.message
          : "Could not update report",
        "error",
      );
      await mutate();
    } finally {
      setBusy(false);
    }
  }

  async function createShare(versionId: string) {
    try {
      const result = await shareSavedChatReportVersion(versionId);
      const url = `${window.location.origin}/reports/shared/${result.token}`;
      setShareLink({ versionId, url });
      await navigator.clipboard.writeText(url);
      await mutate();
      toast("Fixed-version link copied", "success");
    } catch (shareError) {
      toast(
        shareError instanceof Error
          ? shareError.message
          : "Could not share report",
        "error",
      );
    }
  }

  async function revokeShare(versionId: string) {
    try {
      await revokeSavedChatReportVersionShare(versionId);
      if (shareLink?.versionId === versionId) setShareLink(null);
      await mutate();
      toast("Share link revoked", "success");
    } catch (shareError) {
      toast(
        shareError instanceof Error
          ? shareError.message
          : "Could not revoke share link",
        "error",
      );
    }
  }

  if (isLoading || !data) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        {error ? (
          <p className="text-sm text-[var(--color-error)]">Report not found.</p>
        ) : (
          <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
        )}
      </div>
    );
  }

  return (
    <div className="min-h-screen p-5 md:p-8">
      <div className="mx-auto max-w-7xl">
        <Link
          href="/reports"
          className="inline-flex items-center gap-2 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Reports
        </Link>
        <div className="mt-5 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-[var(--color-text)]">
              <KindIcon kind={data.kind} />
              <h1 className="text-2xl">{data.title}</h1>
            </div>
            <p className="mt-2 text-sm text-[var(--color-text-dim)]">
              {data.project_name || "No project"} · {data.original_thread_title}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              href={`/chats/${data.original_thread_id}?report=${data.id}&version=${data.current_version_id}`}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              Follow Up in thread
            </Link>
            <button
              type="button"
              disabled={busy}
              onClick={() => void beginRefresh()}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] disabled:opacity-50"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`}
              />
              Refresh data
            </button>
            {bootstrap?.enterprise_features.organization_sharing &&
              selectedVersion && (
                <button
                  type="button"
                  onClick={() =>
                    void (data.active_share_version_ids.includes(
                      selectedVersion.id,
                    )
                      ? revokeShare(selectedVersion.id)
                      : createShare(selectedVersion.id))
                  }
                  className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--color-text)] px-3 py-2 text-xs text-[var(--color-bg)]"
                >
                  <Share2 className="h-3.5 w-3.5" />
                  {data.active_share_version_ids.includes(selectedVersion.id)
                    ? `Revoke version ${selectedVersion.ordinal} link`
                    : `Share version ${selectedVersion.ordinal}`}
                </button>
              )}
          </div>
        </div>
        {shareLink && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--color-success)]/30 bg-[var(--color-bg-card)] p-3 text-xs text-[var(--color-success)]">
            <span className="truncate">{shareLink.url}</span>
            <button
              type="button"
              onClick={() => void revokeShare(shareLink.versionId)}
              className="text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            >
              Revoke
            </button>
          </div>
        )}
        {data.refresh && (
          <div className="mt-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Clock3 className="h-4 w-4 text-[var(--color-text-dim)]" />
              <span className="text-sm text-[var(--color-text)]">
                {refreshLabel(data.refresh.status)}
              </span>
              {data.refresh.run_id && (
                <Link
                  href={`/chats/${data.original_thread_id}`}
                  className="text-xs text-[var(--color-text-muted)] underline"
                >
                  View live run
                </Link>
              )}
            </div>
            <p className="mt-2 text-xs leading-5 text-[var(--color-text-dim)]">
              {data.refresh.explanation}
            </p>
            {data.refresh.status === "update_available" &&
              data.refresh.candidate_artifact_ids.map((artifactId) => (
                <button
                  type="button"
                  key={artifactId}
                  disabled={busy}
                  onClick={() => void publishCandidate(artifactId)}
                  className="mt-3 mr-2 rounded-xl bg-[var(--color-text)] px-3 py-2 text-xs text-[var(--color-bg)] disabled:opacity-50"
                >
                  Update report
                </button>
              ))}
          </div>
        )}
        <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1fr)_260px]">
          <main className="min-w-0">
            {selectedVersion && (
              <>
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm text-[var(--color-text)]">
                      Version {selectedVersion.ordinal}
                      {selectedVersion.id === data.current_version_id
                        ? " · Current"
                        : ""}
                    </p>
                    <p className="mt-1 text-xs text-[var(--color-text-dim)]">
                      Published{" "}
                      {new Date(selectedVersion.published_at).toLocaleString()}
                    </p>
                  </div>
                  <VersionDownload version={selectedVersion} />
                </div>
                <ReportContentPreview
                  kind={selectedVersion.kind}
                  snapshot={selectedVersion.snapshot}
                  filename={selectedVersion.filename}
                  versionId={selectedVersion.id}
                />
              </>
            )}
          </main>
          <aside className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-3">
            <h2 className="px-2 py-1 text-xs uppercase tracking-[0.16em] text-[var(--color-text-dim)]">
              Version history
            </h2>
            <div className="mt-2 space-y-1">
              {data.versions.map((version) => (
                <button
                  type="button"
                  key={version.id}
                  onClick={() => setSelectedVersionId(version.id)}
                  className={`w-full rounded-xl px-3 py-2 text-left ${
                    selectedVersion?.id === version.id
                      ? "bg-[var(--color-bg-hover)]"
                      : "hover:bg-[var(--color-bg)]"
                  }`}
                >
                  <div className="flex items-center justify-between text-xs text-[var(--color-text)]">
                    <span>Version {version.ordinal}</span>
                    {version.id === data.current_version_id && (
                      <Check className="h-3.5 w-3.5 text-[var(--color-success)]" />
                    )}
                  </div>
                  <p className="mt-1 text-[10px] text-[var(--color-text-dim)]">
                    {new Date(version.published_at).toLocaleString()}
                  </p>
                </button>
              ))}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}

export function SharedSavedChatReport({ token }: { token: string }) {
  const { data, error, isLoading } = useSWR(
    `shared-saved-report:${token}`,
    () => getSharedSavedChatReport(token),
  );
  if (isLoading || !data) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        {error ? (
          <p className="text-sm text-[var(--color-text-dim)]">
            Shared report not found.
          </p>
        ) : (
          <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
        )}
      </div>
    );
  }
  return (
    <div className="min-h-screen p-5 md:p-8">
      <div className="mx-auto max-w-6xl">
        <Link
          href="/reports"
          className="inline-flex items-center gap-2 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Reports
        </Link>
        <div className="mt-5 flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-[var(--color-text)]">
              <KindIcon kind={data.kind} />
              <h1 className="text-2xl">{data.title}</h1>
            </div>
            <p className="mt-2 text-sm text-[var(--color-text-dim)]">
              Shared fixed version · Version {data.version.ordinal}
            </p>
          </div>
          <VersionDownload version={data.version} />
        </div>
        <div className="mt-5 flex flex-wrap gap-2 text-[10px]">
          {data.version.freshness_state !== "unknown" && (
            <span
              className={`rounded-full border px-2 py-1 ${freshnessTone(data.version.freshness_state)}`}
            >
              {freshnessLabel(
                data.version.freshness_state,
                data.version.freshness_at,
              )}
            </span>
          )}
          <span className="rounded-full border border-[var(--color-border)] px-2 py-1 text-[var(--color-text-dim)]">
            Checked{" "}
            {new Date(data.version.freshness_checked_at).toLocaleString()}
          </span>
        </div>
        <div className="mt-6">
          <ReportContentPreview
            kind={data.version.kind}
            snapshot={data.version.snapshot}
            filename={data.version.filename}
            versionId={data.version.id}
          />
        </div>
      </div>
    </div>
  );
}
