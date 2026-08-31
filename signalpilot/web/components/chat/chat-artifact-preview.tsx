"use client";

// Artifact preview cards for the standalone data chat.

import {
  AlertCircle,
  ArrowDownToLine,
  FileChartColumn,
  Maximize2,
  Table2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { VegaEmbed } from "react-vega";
import type { VisualizationSpec } from "vega-embed";
import {
  downloadStandaloneArtifact,
  getStandaloneArtifactObjectUrl,
  type StandaloneChatArtifact,
} from "~/lib/api";
import { ArtifactLightbox } from "~/components/chat/artifact-lightbox";
import { StandaloneArtifactContext } from "~/components/chat/standalone-artifact-context";
import { SaveArtifactAsReportAction } from "~/components/chat/chat-save-report-action";
import { useToast } from "~/components/ui/toast";

export type ArtifactPreviewData = Pick<
  StandaloneChatArtifact,
  | "id"
  | "assistant_message_id"
  | "kind"
  | "filename"
  | "mime_type"
  | "snapshot"
  | "freshness_at"
  | "assumptions"
  | "exclusions"
  | "caveats"
  | "saved_report_id"
  | "saved_report_version_id"
  | "saved_report_title"
  | "report_action"
  | "created_at"
  | "download_formats"
>;

type ArtifactDownload = (
  artifactId: string,
  format: string,
  filename: string,
) => Promise<void>;

function RuntimeChartPreview({
  artifactId,
  filename,
}: {
  artifactId: string;
  filename: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    void getStandaloneArtifactObjectUrl(artifactId, "png")
      .then((value) => {
        objectUrl = value;
        if (active) setUrl(value);
      })
      .catch(() => setUrl(null));
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [artifactId]);
  return url ? (
    <>
      <button
        type="button"
        title="Click to view full size"
        aria-label={`View ${filename} full size`}
        onClick={() => {
          setZoomed(false);
          setViewerOpen(true);
        }}
        className="group relative mx-auto block cursor-zoom-in"
      >
        <img
          src={url}
          alt={filename}
          className="mx-auto max-h-[520px] max-w-full"
        />
        <span className="absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)]/90 text-[var(--color-text-muted)] opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
          <Maximize2 className="h-3.5 w-3.5" />
        </span>
      </button>
      <ArtifactLightbox
        open={viewerOpen}
        title={filename}
        onClose={() => setViewerOpen(false)}
      >
        <img
          src={url}
          alt={filename}
          onClick={() => setZoomed((value) => !value)}
          className={
            zoomed
              ? "max-w-none cursor-zoom-out"
              : "max-h-full max-w-full cursor-zoom-in object-contain"
          }
        />
      </ArtifactLightbox>
    </>
  ) : (
    <div className="flex min-h-64 items-center justify-center text-xs text-[var(--color-text-dim)]">
      Loading chart preview…
    </div>
  );
}

/** Header button that opens an artifact in the fullscreen viewer. */
function ExpandButton({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      data-testid="artifact-expand"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] px-2 py-1 text-[11px] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
    >
      <Maximize2 className="h-3 w-3" />
      Expand
    </button>
  );
}

function ArtifactDownloads({
  artifact,
  onDownload,
  canSaveAsReport = false,
}: {
  artifact: ArtifactPreviewData;
  onDownload: ArtifactDownload;
  canSaveAsReport?: boolean;
}) {
  const { toast } = useToast();
  return (
    <div className="flex flex-wrap items-center gap-2">
      {canSaveAsReport && <SaveArtifactAsReportAction artifact={artifact} />}
      {artifact.download_formats.map((format) => (
        <button
          key={format}
          type="button"
          onClick={() =>
            onDownload(artifact.id, format, artifact.filename).catch(() =>
              toast("Download failed", "error"),
            )
          }
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] px-2 py-1 text-[11px] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
        >
          <ArrowDownToLine className="h-3 w-3" />
          {format.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

export function ArtifactPreview({
  artifact,
  onDownload = downloadStandaloneArtifact,
  canSaveAsReport = false,
}: {
  artifact: ArtifactPreviewData;
  onDownload?: ArtifactDownload;
  canSaveAsReport?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [viewerOpen, setViewerOpen] = useState(false);
  const snapshot = artifact.snapshot;
  if (artifact.kind === "table") {
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
      ? (snapshot.rows.filter(
          (row): row is Record<string, unknown> =>
            typeof row === "object" && row !== null,
        ) as Record<string, unknown>[])
      : [];
    return (
      <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        <div className="flex items-center justify-between gap-4 border-b border-[var(--color-border)] px-3 py-2">
          <div className="flex min-w-0 items-center gap-2">
            <Table2 className="h-3.5 w-3.5 text-[var(--color-text-dim)]" />
            <span className="truncate text-xs text-[var(--color-text)]">
              {artifact.filename}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {rows.length > 12 && (
              <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                className="rounded-lg border border-[var(--color-border)] px-2 py-1 text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
              >
                {expanded ? "Collapse" : "Open"}
              </button>
            )}
            <ArtifactDownloads
              artifact={artifact}
              onDownload={onDownload}
              canSaveAsReport={canSaveAsReport}
            />
          </div>
        </div>
        <div
          className={`${expanded ? "max-h-[70vh]" : "max-h-72"} overflow-auto`}
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
              {rows.slice(0, expanded ? rows.length : 12).map((row, index) => (
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
        {Boolean(snapshot.truncated) && (
          <p className="border-t border-[var(--color-border)] px-3 py-2 text-[11px] text-[var(--color-warning)]">
            Preview and download are limited by the governed query row limit.
          </p>
        )}
        <StandaloneArtifactContext artifact={artifact} />
      </div>
    );
  }
  if (artifact.kind === "chart") {
    const rows = Array.isArray(snapshot.rows) ? snapshot.rows : [];
    const baseSpec =
      typeof snapshot.spec === "object" && snapshot.spec ? snapshot.spec : {};
    const spec = {
      ...baseSpec,
      data: { values: rows },
      width: 640,
      height: 400,
      autosize: { type: "fit", contains: "padding", resize: true },
    } as VisualizationSpec;
    const display =
      typeof snapshot.display === "object" && snapshot.display
        ? snapshot.display
        : {};
    const displayLimited = "limited" in display && display.limited === true;
    const categoryLimit =
      "category_limit" in display && typeof display.category_limit === "number"
        ? display.category_limit
        : 24;
    const legendLimit =
      "legend_limit" in display && typeof display.legend_limit === "number"
        ? display.legend_limit
        : 8;
    return (
      <div
        data-testid="standalone-chart-artifact"
        data-filename={artifact.filename}
        className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]"
      >
        <div className="flex items-center justify-between gap-4 border-b border-[var(--color-border)] px-3 py-2">
          <div className="flex min-w-0 items-center gap-2">
            <FileChartColumn className="h-3.5 w-3.5 text-[var(--color-text-dim)]" />
            <span className="truncate text-xs text-[var(--color-text)]">
              {artifact.filename}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {snapshot.runtime_png !== true && (
              <ExpandButton
                label={`Expand ${artifact.filename}`}
                onClick={() => setViewerOpen(true)}
              />
            )}
            <ArtifactDownloads
              artifact={artifact}
              onDownload={onDownload}
              canSaveAsReport={canSaveAsReport}
            />
          </div>
        </div>
        <div className="min-h-64 overflow-x-auto p-4">
          {snapshot.runtime_png === true ? (
            <RuntimeChartPreview
              artifactId={artifact.id}
              filename={artifact.filename}
            />
          ) : (
            <div className="mx-auto w-fit min-w-[640px]">
              <VegaEmbed
                spec={spec}
                options={{ actions: false, mode: "vega-lite", renderer: "svg" }}
              />
            </div>
          )}
        </div>
        {viewerOpen && snapshot.runtime_png !== true && (
          <ArtifactLightbox
            open={viewerOpen}
            title={artifact.filename}
            onClose={() => setViewerOpen(false)}
          >
            <div className="rounded-xl bg-[var(--color-bg-card)] p-6">
              <VegaEmbed
                spec={{
                  ...spec,
                  width: Math.max(
                    640,
                    Math.floor(
                      (typeof window !== "undefined"
                        ? window.innerWidth
                        : 1280) * 0.78,
                    ),
                  ),
                  height: Math.max(
                    400,
                    Math.floor(
                      (typeof window !== "undefined"
                        ? window.innerHeight
                        : 800) * 0.66,
                    ),
                  ),
                }}
                options={{ actions: false, mode: "vega-lite", renderer: "svg" }}
              />
            </div>
          </ArtifactLightbox>
        )}
        {displayLimited && (
          <p className="border-t border-[var(--color-border)] px-3 py-2 text-[11px] text-[var(--color-text-muted)]">
            Preview shows up to {categoryLimit} categories and {legendLimit}{" "}
            series. The CSV includes the full saved row snapshot.
          </p>
        )}
        {Boolean(snapshot.truncated) && (
          <p className="border-t border-[var(--color-border)] px-3 py-2 text-[11px] text-[var(--color-warning)]">
            The chart uses a row-limited data snapshot.
          </p>
        )}
        <StandaloneArtifactContext artifact={artifact} />
      </div>
    );
  }
  const html = typeof snapshot.html === "string" ? snapshot.html : "";
  const reportBody =
    /<body(?:\s[^>]*)?>([\s\S]*?)<\/body>/i.exec(html)?.[1] ?? html;
  const hasRenderableReport = Boolean(
    reportBody
      .replace(/<style(?:\s[^>]*)?>[\s\S]*?<\/style>/gi, "")
      .replace(/<!--[\s\S]*?-->/g, "")
      .trim(),
  );
  return (
    <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]">
      <div className="flex items-center justify-between gap-4 border-b border-[var(--color-border)] px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <FileChartColumn className="h-3.5 w-3.5 text-[var(--color-text-dim)]" />
          <span className="truncate text-xs text-[var(--color-text)]">
            {artifact.filename}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {hasRenderableReport && (
            <ExpandButton
              label={`Expand ${artifact.filename}`}
              onClick={() => setViewerOpen(true)}
            />
          )}
          <ArtifactDownloads
            artifact={artifact}
            onDownload={onDownload}
            canSaveAsReport={canSaveAsReport}
          />
        </div>
      </div>
      {hasRenderableReport ? (
        <>
          <iframe
            title={artifact.filename}
            sandbox=""
            referrerPolicy="no-referrer"
            srcDoc={html}
            className="h-[440px] w-full border-0 bg-white"
          />
          <ArtifactLightbox
            open={viewerOpen}
            title={artifact.filename}
            onClose={() => setViewerOpen(false)}
          >
            <iframe
              title={`${artifact.filename} (expanded)`}
              sandbox=""
              referrerPolicy="no-referrer"
              srcDoc={html}
              className="h-full max-h-[86vh] w-[92vw] rounded-xl border-0 bg-white"
            />
          </ArtifactLightbox>
        </>
      ) : (
        <div className="flex min-h-48 items-center justify-center px-6 py-10 text-center">
          <div className="max-w-sm">
            <AlertCircle className="mx-auto h-5 w-5 text-[var(--color-warning)]" />
            <p className="mt-3 text-sm text-[var(--color-text)]">
              This report has no renderable content.
            </p>
            <p className="mt-1 text-xs leading-5 text-[var(--color-text-dim)]">
              Ask Data Chat to regenerate the report to create a new artifact.
            </p>
          </div>
        </div>
      )}
      <StandaloneArtifactContext artifact={artifact} />
    </div>
  );
}
