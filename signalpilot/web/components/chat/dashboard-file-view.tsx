"use client";

import { AlertCircle, ArrowDownToLine, Maximize2, Upload } from "lucide-react";
import { useContext, useMemo, useState } from "react";
import type { ConversationFileInfo } from "~/lib/api";
import { normalizeFileRef, resolveFileRef } from "~/lib/chat-file-refs";
import type { PublishedDashboard } from "~/lib/api/dashboards";
import {
  DashboardPublishDialog,
  DashboardPublishedStrip,
  useDashboardPublishApi,
  usePublishedDashboard,
} from "~/components/chat/dashboard-publish-dialog";
import type { DashboardPublishApi } from "~/components/chat/dashboard-publish-form";
import {
  DashboardRenderer,
  datasetFileRefs,
  inlineDatasets,
  parseDatasetCsv,
  validateDashboardSpec,
  type DashboardSpec,
  type DashboardTheme,
  type DatasetRows,
  type FilterState,
} from "~/dashboard-renderer";
import { ArtifactLightbox } from "~/components/chat/artifact-lightbox";
import { ChatCode } from "~/components/chat/chat-code";
import { ChatUiContext } from "~/components/chat/chat-ui-context";
import { downloadUiFile } from "~/components/chat/download-ui-file";
import { PendingFigure } from "~/components/chat/markdown/image";
import { useFileTexts } from "~/components/chat/use-file-text";
import { useToast } from "~/components/ui/toast";

/** Cap on the raw JSON shown behind "Show raw"; the spec itself is parsed in full. */
const MAX_RAW_CHARS = 200_000;

type ParsedSpec = { spec: DashboardSpec; errors: null } | { spec: null; errors: string[] };

/** Parse and validate the dashboard JSON; every failure is a message list. */
export function parseDashboardFile(text: string): ParsedSpec {
  let input: unknown;
  try {
    input = JSON.parse(text);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return { spec: null, errors: [`The file is not valid JSON: ${detail}`] };
  }
  const result = validateDashboardSpec(input);
  if (result.ok) return { spec: result.spec, errors: null };
  return { spec: null, errors: result.errors };
}

/**
 * The chat chrome is dark unless the document opts into light. There is no
 * runtime theme toggle today, so a `data-theme` / `light` class on the root
 * is the only signal; otherwise the dashboard matches the dark chrome.
 */
export function resolveDashboardTheme(root: HTMLElement | null = typeof document === "undefined" ? null : document.documentElement): DashboardTheme {
  if (!root) return "dark";
  const declared = root.dataset.theme ?? (root.classList.contains("light") ? "light" : null);
  return declared === "light" ? "light" : "dark";
}

function ErrorBand({ errors }: { errors: string[] }) {
  return (
    <div
      role="alert"
      data-testid="chat-dashboard-errors"
      className="mb-2 rounded-md border border-[var(--color-error)]/30 bg-[var(--color-error)]/5 px-3 py-2 text-[11.5px] leading-5 text-[var(--color-error)]"
    >
      <p className="flex items-center gap-1.5 font-medium">
        <AlertCircle className="h-3.5 w-3.5 flex-none" />
        This dashboard cannot be rendered.
      </p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 font-mono text-[10.5px]">
        {errors.map((error, index) => (
          <li key={index}>{error}</li>
        ))}
      </ul>
    </div>
  );
}

function RawJson({ text }: { text: string }) {
  const truncated = text.length > MAX_RAW_CHARS;
  return (
    <>
      <ChatCode
        code={truncated ? text.slice(0, MAX_RAW_CHARS) : text}
        language="text"
        maxHeightClass="max-h-[60vh]"
      />
      {truncated && (
        <p className="px-3.5 py-2 text-[11px] text-[var(--color-text-dim)]">
          Raw view truncated to the first {MAX_RAW_CHARS.toLocaleString()} characters.
        </p>
      )}
    </>
  );
}

const ACTION_CLASS =
  "inline-flex flex-none items-center gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-2 py-1 text-[11px] text-[var(--color-text-muted)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]";

/**
 * Renders a `*.dashboard.json` conversation file: validates the spec,
 * resolves each SQL dataset's snapshot (`artifacts/datasets/<name>.csv`)
 * against the manifest, fetches and parses them, then hands everything to
 * the shared DashboardRenderer with live filters. Missing snapshots are
 * left out of the map so the renderer reports them per tile; while the run
 * still streams they show as pending.
 */
export function DashboardFileView({
  file,
  text,
  files,
  running,
  publishApi,
}: {
  file: ConversationFileInfo;
  text: string;
  files: readonly ConversationFileInfo[];
  running: boolean;
  /** Dashboards API for the publish flow; tests and the fixture harness
   * inject a fake, live pages use the real module. */
  publishApi?: DashboardPublishApi | null;
}) {
  const ui = useContext(ChatUiContext);
  const { toast } = useToast();
  const conversationId = ui?.conversationId ?? "";
  const parsed = useMemo(() => parseDashboardFile(text), [text]);
  const [showRaw, setShowRaw] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const api = useDashboardPublishApi(publishApi);
  const publishedState = usePublishedDashboard(api, conversationId, file.id);
  // null = closed; "new" = fresh publish; an id = new version of that one.
  const [publishTarget, setPublishTarget] = useState<"new" | string | null>(null);
  const onPublished = ({ dashboard }: { dashboard: PublishedDashboard }) => {
    publishedState.setPublished(dashboard);
    setPublishTarget(null);
    toast("Published", "success");
  };
  const [filterState, setFilterState] = useState<FilterState>({});
  const [theme] = useState<DashboardTheme>(() => resolveDashboardTheme());

  const spec = parsed.spec;
  const refs = useMemo(() => (spec ? datasetFileRefs(spec) : []), [spec]);
  const resolved = useMemo(
    () =>
      refs.map((ref) => ({
        ...ref,
        file: resolveFileRef(normalizeFileRef(ref.path), files, {
          runId: file.origin_run_id,
        }),
      })),
    [refs, files, file.origin_run_id],
  );
  const datasetFiles = useMemo(
    () =>
      resolved.flatMap((entry) => (entry.file ? [entry.file] : [])),
    [resolved],
  );
  const texts = useFileTexts(conversationId, datasetFiles);

  const datasets = useMemo(() => {
    if (!spec) return {};
    const out: Record<string, DatasetRows> = inlineDatasets(spec);
    for (const entry of resolved) {
      if (!entry.file) continue;
      const state = texts[entry.file.id];
      if (!state || state.phase !== "text") continue;
      out[entry.name] = parseDatasetCsv(state.text);
    }
    return out;
  }, [spec, resolved, texts]);

  const loading = resolved.some(
    (entry) => entry.file && texts[entry.file.id]?.phase === "loading",
  );
  const unresolved = resolved.some((entry) => !entry.file);
  const pending = loading || (running && unresolved);

  const download = () => {
    void downloadUiFile(
      { conversationId: ui?.conversationId ?? null, downloadFile: ui?.downloadFile },
      file,
    ).catch(() => toast("This file is no longer available.", "error"));
  };

  const renderer = spec ? (
    <DashboardRenderer
      spec={spec}
      datasets={datasets}
      theme={theme}
      filterState={filterState}
      onFilterStateChange={setFilterState}
    />
  ) : null;

  return (
    <div data-testid="chat-dashboard-view" data-pending={pending ? "1" : "0"}>
      <div className="flex items-center justify-end gap-1.5 border-b border-[var(--color-border)] px-3 py-1.5">
        {parsed.errors && (
          <button
            type="button"
            data-testid="chat-dashboard-show-raw"
            aria-pressed={showRaw}
            onClick={() => setShowRaw((value) => !value)}
            className={`${ACTION_CLASS} mr-auto`}
          >
            {showRaw ? "Hide raw" : "Show raw"}
          </button>
        )}
        {spec && (
          <button
            type="button"
            data-testid="chat-dashboard-expand"
            aria-label="Expand the dashboard"
            onClick={() => setExpanded(true)}
            className={ACTION_CLASS}
          >
            <Maximize2 className="h-3 w-3" />
            Expand
          </button>
        )}
        {spec && conversationId && (
          <button
            type="button"
            data-testid="chat-dashboard-publish"
            aria-label="Publish the dashboard"
            onClick={() => {
              void publishedState.reload();
              setPublishTarget(publishedState.published?.id ?? "new");
            }}
            className={ACTION_CLASS}
          >
            <Upload className="h-3 w-3" />
            Publish
          </button>
        )}
        <button
          type="button"
          data-testid="chat-dashboard-download"
          aria-label={`Download ${file.filename}`}
          onClick={download}
          className={ACTION_CLASS}
        >
          <ArrowDownToLine className="h-3 w-3" />
          Download JSON
        </button>
      </div>
      {spec && publishedState.published && (
        <DashboardPublishedStrip
          dashboard={publishedState.published}
          onPublishNewVersion={() => setPublishTarget(publishedState.published?.id ?? "new")}
        />
      )}
      {spec && conversationId && (
        <DashboardPublishDialog
          open={publishTarget !== null}
          onClose={() => setPublishTarget(null)}
          conversationId={conversationId}
          file={file}
          spec={spec}
          files={files}
          dashboards={publishedState.dashboards}
          initialTargetId={publishTarget === "new" ? null : publishTarget}
          onPublished={onPublished}
          api={api}
        />
      )}
      <div className="p-2">
        {parsed.errors && <ErrorBand errors={parsed.errors} />}
        {parsed.errors && showRaw && <RawJson text={text} />}
        {spec && pending ? (
          <PendingFigure name={file.filename} />
        ) : (
          renderer
        )}
      </div>
      {spec && (
        <ArtifactLightbox
          open={expanded}
          title={spec.title}
          onClose={() => setExpanded(false)}
        >
          <div
            data-testid="chat-dashboard-expanded"
            className="max-h-[86vh] w-[92vw] max-w-[1400px] overflow-auto rounded-md"
          >
            {renderer}
          </div>
        </ArtifactLightbox>
      )}
    </div>
  );
}
