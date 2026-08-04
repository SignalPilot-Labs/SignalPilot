"use client";

import {
  AlertCircle,
  ArrowDownToLine,
  ChevronRight,
  CircleStop,
  Copy,
  FileChartColumn,
  Loader2,
  MessageSquarePlus,
  MoreHorizontal,
  PanelLeft,
  Play,
  Share2,
  Sparkles,
  Table2,
  Trash2,
  Wrench,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import ReactMarkdown from "react-markdown";
import { VegaEmbed } from "react-vega";
import remarkGfm from "remark-gfm";
import useSWR, { useSWRConfig } from "swr";
import type { VisualizationSpec } from "vega-embed";
import {
  archiveStandaloneConversation,
  cancelStandaloneRun,
  clarifyStandaloneRun,
  createStandaloneConversation,
  createStandaloneRun,
  decideStandaloneQueryProposal,
  downloadStandaloneArtifact,
  getStandaloneArtifactObjectUrl,
  getStandaloneChatBootstrap,
  getStandaloneChatProjectReadiness,
  getStandaloneConversation,
  listStandaloneConversations,
  openStandaloneNotebookArchive,
  renameStandaloneConversation,
  retryStandaloneRun,
  revokeStandaloneConversationShare,
  setDefaultStandaloneChatProject,
  shareStandaloneConversation,
  streamStandaloneRunEvents,
  type StandaloneChatArtifact,
  type StandaloneChatEvent,
  type StandaloneChatMessage,
  type StandaloneChatRunStatus,
  type StandaloneConversation,
  type StandaloneConversationDetail,
} from "~/lib/api";
import { StandaloneArtifactContext } from "~/components/chat/standalone-artifact-context";
import { StandaloneChatComposer } from "~/components/chat/standalone-chat-composer";
import { useToast } from "~/components/ui/toast";
import {
  appendOptimisticUserMessage,
  applyStandaloneChatEvent,
  assembleStandaloneRunText,
  containsStandaloneSubmission,
  isStandaloneRunReconciled,
  standaloneMessageKey,
  upsertStandaloneConversation,
  type OptimisticUserMessage,
} from "~/lib/standalone-chat-state";

type UiMessage = StandaloneChatMessage & {
  runId?: string;
  runStatus?: StandaloneChatRunStatus;
  synthetic?: boolean;
};

type ChatUiContextValue = {
  events: StandaloneChatEvent[];
  artifacts: StandaloneChatArtifact[];
  onStop: (runId: string) => Promise<void>;
  onRetry: (runId: string) => Promise<void>;
};

const ChatUiContext = createContext<ChatUiContextValue | null>(null);

function useChatUi() {
  const value = useContext(ChatUiContext);
  if (!value) throw new Error("Standalone chat UI context is missing");
  return value;
}

function statusLabel(status: StandaloneChatRunStatus | null): string | null {
  if (!status) return null;
  return {
    queued: "Queued",
    running: "Running",
    waiting_for_user: "Waiting for you",
    waiting_for_query_approval: "Waiting for query approval",
    completed: "Completed",
    failed: "Failed",
    cancelled: "Stopped",
  }[status];
}

function statusTone(status: StandaloneChatRunStatus | null): string {
  if (status === "running" || status === "queued")
    return "text-[var(--color-success)]";
  if (status === "waiting_for_user" || status === "waiting_for_query_approval")
    return "text-[var(--color-warning)]";
  if (status === "failed") return "text-[var(--color-error)]";
  return "text-[var(--color-text-dim)]";
}

function isStreamingStatus(status: StandaloneChatRunStatus | undefined) {
  return status === "queued" || status === "running";
}

function projectSetupSuffix(message: string): string {
  const normalized = message.toLowerCase();
  if (normalized.includes("ai runtime credentials")) {
    return " · AI setup needed";
  }
  if (normalized.includes("dbt metadata")) {
    return " · dbt metadata needed";
  }
  if (normalized.includes("connection")) {
    return " · connection setup needed";
  }
  if (normalized.includes("branch")) {
    return " · branch setup needed";
  }
  return " · setup needed";
}

function eventText(
  event: StandaloneChatEvent | null | undefined,
  key: string,
): string {
  const value = event?.payload?.[key];
  return typeof value === "string" ? value : "";
}

function WorkTimeline({ runId }: { runId: string }) {
  const { events } = useChatUi();
  const work = events.filter(
    (event) => event.run_id === runId && event.type !== "text_delta",
  );
  if (!work.length) {
    return (
      <p className="text-xs text-[var(--color-text-dim)]">
        Work details will appear as the analysis progresses.
      </p>
    );
  }
  return (
    <ol className="space-y-2" aria-label="Analysis work">
      {work.map((event) => {
        const label =
          eventText(event, "label") ||
          eventText(event, "message") ||
          eventText(event, "tool") ||
          eventText(event, "filename") ||
          event.type.replaceAll("_", " ");
        const expandable =
          event.type === "tool_started" ||
          event.type === "tool_completed" ||
          event.type === "source" ||
          event.type === "intermediate_result" ||
          event.type === "sql" ||
          event.type === "error";
        const summary = eventText(event, "summary");
        return (
          <li
            key={`${event.run_id}-${event.sequence}`}
            className="relative pl-5 text-xs text-[var(--color-text-muted)]"
          >
            <span className="absolute left-0 top-1.5 h-1.5 w-1.5 rounded-full bg-[var(--color-border-active)]" />
            {expandable ? (
              <details>
                <summary className="select-none hover:text-[var(--color-text)]">
                  {label}
                </summary>
                <pre className="mt-2 max-h-56 overflow-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-[11px] leading-relaxed text-[var(--color-text-dim)]">
                  {JSON.stringify(event.payload, null, 2)}
                </pre>
              </details>
            ) : (
              <span>
                {label}
                {summary && summary !== label && (
                  <span className="mt-0.5 block text-[var(--color-text-dim)]">
                    {summary}
                  </span>
                )}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

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
    <img
      src={url}
      alt={filename}
      className="mx-auto max-h-[520px] max-w-full"
    />
  ) : (
    <div className="flex min-h-64 items-center justify-center text-xs text-[var(--color-text-dim)]">
      Loading chart preview…
    </div>
  );
}

function ArtifactDownloads({
  artifact,
  onDownload,
}: {
  artifact: ArtifactPreviewData;
  onDownload: ArtifactDownload;
}) {
  const { toast } = useToast();
  return (
    <div className="flex flex-wrap items-center gap-2">
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
}: {
  artifact: ArtifactPreviewData;
  onDownload?: ArtifactDownload;
}) {
  const [expanded, setExpanded] = useState(false);
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
            <ArtifactDownloads artifact={artifact} onDownload={onDownload} />
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
          <ArtifactDownloads artifact={artifact} onDownload={onDownload} />
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
        <ArtifactDownloads artifact={artifact} onDownload={onDownload} />
      </div>
      {hasRenderableReport ? (
        <iframe
          title={artifact.filename}
          sandbox=""
          referrerPolicy="no-referrer"
          srcDoc={html}
          className="h-[440px] w-full border-0 bg-white"
        />
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

function AssistantMessage({ message }: { message: UiMessage }) {
  const runId =
    message.runId ??
    (typeof message.metadata.run_id === "string"
      ? message.metadata.run_id
      : "");
  const runStatus =
    message.runStatus ??
    (typeof message.metadata.status === "string"
      ? (message.metadata.status as StandaloneChatRunStatus)
      : "completed");
  const [showWork, setShowWork] = useState(false);
  const { artifacts, onRetry, onStop } = useChatUi();
  const { toast } = useToast();
  const attachedArtifacts = artifacts.filter(
    (artifact) =>
      artifact.assistant_message_id === message.id || artifact.run_id === runId,
  );
  const successful = runStatus === "completed";
  const running = runStatus === "queued" || runStatus === "running";
  const runtimeArchiveAvailable =
    message.metadata.runtime_archive_available === true;
  return (
    <article
      data-chat-message-id={message.id}
      className="group mx-auto w-full max-w-3xl px-6 py-5"
    >
      <div className="flex gap-3">
        <div className="mt-0.5 flex h-7 w-7 flex-none items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          {running ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--color-success)]" />
          ) : runStatus === "failed" ? (
            <AlertCircle className="h-3.5 w-3.5 text-[var(--color-error)]" />
          ) : (
            <Sparkles className="h-3.5 w-3.5 text-[var(--color-text-muted)]" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="chat-markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          </div>
          {attachedArtifacts.length > 0 && (
            <div className="mt-5 space-y-4">
              {attachedArtifacts.map((artifact) => (
                <ArtifactPreview key={artifact.id} artifact={artifact} />
              ))}
            </div>
          )}
          {runStatus === "failed" && (
            <p className="mt-3 text-xs text-[var(--color-error)]">
              The run failed before a completed answer was produced.
            </p>
          )}
          {runStatus === "cancelled" && (
            <p className="mt-3 text-xs text-[var(--color-text-dim)]">
              This run was stopped. Completed work remains available below.
            </p>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {successful && (
              <button
                type="button"
                onClick={() =>
                  void navigator.clipboard
                    .writeText(message.content)
                    .catch(() => toast("Could not copy answer", "error"))
                }
                className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
              >
                <Copy className="h-3 w-3" />
                Copy
              </button>
            )}
            {runId && (
              <button
                type="button"
                onClick={() => {
                  if (runtimeArchiveAvailable) {
                    void openStandaloneNotebookArchive(runId).catch(() =>
                      toast("Archived notebook is unavailable", "error"),
                    );
                  } else {
                    setShowWork((value) => !value);
                  }
                }}
                className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
              >
                <Wrench className="h-3 w-3" />
                View work
                {!runtimeArchiveAvailable && (
                  <ChevronRight
                    className={`h-3 w-3 transition-transform ${showWork ? "rotate-90" : ""}`}
                  />
                )}
              </button>
            )}
            {running && runId && (
              <button
                type="button"
                onClick={() => void onStop(runId)}
                className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-error)]"
              >
                <CircleStop className="h-3 w-3" />
                Stop
              </button>
            )}
            {runStatus === "failed" && runId && (
              <button
                type="button"
                onClick={() => void onRetry(runId)}
                className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
              >
                <Play className="h-3 w-3" />
                Retry
              </button>
            )}
          </div>
          {showWork && runId && !runtimeArchiveAvailable && (
            <div className="mt-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
              <WorkTimeline runId={runId} />
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

function UserMessage({ message }: { message: UiMessage }) {
  return (
    <article
      data-chat-message-id={message.id}
      className="mx-auto w-full max-w-3xl px-6 py-4"
    >
      <div className="ml-auto max-w-[78%] rounded-2xl rounded-br-md border border-[var(--color-border)] bg-[var(--color-bg-elevated)] px-4 py-3 text-sm leading-6 text-[var(--color-text)]">
        <div className="whitespace-pre-wrap">{message.content}</div>
      </div>
    </article>
  );
}

function ChatMessage({ message }: { message: UiMessage }) {
  return message.role === "user" ? (
    <UserMessage message={message} />
  ) : (
    <AssistantMessage message={message} />
  );
}

function StarterQuestions({
  questions,
  onSelect,
}: {
  questions: string[];
  onSelect: (question: string) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {questions.slice(0, 4).map((question) => (
        <button
          key={question}
          type="button"
          onClick={() => {
            onSelect(question);
            requestAnimationFrame(() =>
              document
                .querySelector<HTMLTextAreaElement>("[data-chat-composer]")
                ?.focus(),
            );
          }}
          className="min-h-24 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4 text-left text-sm leading-5 text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
        >
          {question}
        </button>
      ))}
    </div>
  );
}

function ReadinessNotice({
  message,
  showSetup,
  onSetup,
}: {
  message: string;
  showSetup: boolean;
  onSetup: () => void;
}) {
  return (
    <div className="rounded-xl border border-[var(--color-warning)]/20 bg-[var(--color-bg-card)] p-4 text-sm text-[var(--color-warning)]">
      <p>{message}</p>
      {showSetup && (
        <button
          type="button"
          onClick={onSetup}
          className="mt-3 rounded-lg border border-[var(--color-warning)]/30 px-3 py-1.5 text-xs hover:bg-[var(--color-bg-hover)]"
        >
          Open project setup
        </button>
      )}
    </div>
  );
}

function ConversationRail({
  conversations,
  activeId,
  historyLoading,
  loadingConversationId,
  onNewConversation,
  onSelectConversation,
  onPrefetchConversation,
  onRename,
  onArchive,
  onShare,
  onRevokeShare,
  sharingEnabled,
}: {
  conversations: StandaloneConversation[];
  activeId?: string;
  historyLoading: boolean;
  loadingConversationId: string | null;
  onNewConversation: () => void;
  onSelectConversation: (conversationId: string) => void;
  onPrefetchConversation: (conversationId: string) => void;
  onRename: (conversation: StandaloneConversation) => void;
  onArchive: (conversation: StandaloneConversation) => void;
  onShare: (conversation: StandaloneConversation) => void;
  onRevokeShare: (conversation: StandaloneConversation) => void;
  sharingEnabled: boolean;
}) {
  const [menuId, setMenuId] = useState<string | null>(null);
  return (
    <aside className="flex w-72 flex-none flex-col border-r border-[var(--color-border)] bg-[var(--color-sidebar)]">
      <div className="p-3 pr-7">
        <button
          type="button"
          onClick={onNewConversation}
          className="flex w-full items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-2.5 text-sm text-[var(--color-text)] hover:border-[var(--color-border-hover)]"
        >
          <MessageSquarePlus className="h-4 w-4" />
          New chat
        </button>
      </div>
      <div className="px-3 pb-2 text-[10px] uppercase tracking-[0.16em] text-[var(--color-text-dim)]">
        Your chats
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {historyLoading && conversations.length === 0 ? (
          <div
            aria-label="Loading chat history"
            role="status"
            className="space-y-2 px-2 py-1"
          >
            {[0, 1, 2, 3].map((index) => (
              <div
                key={index}
                className="h-14 animate-pulse rounded-xl bg-[var(--color-bg-card)]"
              />
            ))}
          </div>
        ) : conversations.length === 0 ? (
          <p className="px-3 py-4 text-xs text-[var(--color-text-dim)]">
            Your private conversations will appear here.
          </p>
        ) : (
          conversations.map((conversation) => (
            <div
              key={conversation.id}
              className={`group relative mb-1 rounded-xl ${
                conversation.id === activeId
                  ? "bg-[var(--color-bg-hover)]"
                  : "hover:bg-[var(--color-bg-card)]"
              }`}
            >
              <button
                type="button"
                onPointerEnter={() => onPrefetchConversation(conversation.id)}
                onFocus={() => onPrefetchConversation(conversation.id)}
                onClick={() => onSelectConversation(conversation.id)}
                className="w-full px-3 py-2.5 pr-9 text-left"
              >
                <div className="flex items-center gap-2 text-[13px] text-[var(--color-text)]">
                  <span className="min-w-0 flex-1 truncate">
                    {conversation.title}
                  </span>
                  {loadingConversationId === conversation.id && (
                    <Loader2 className="h-3 w-3 flex-none animate-spin text-[var(--color-text-dim)]" />
                  )}
                </div>
                <div className="mt-1 flex items-center gap-2 text-[10px]">
                  <span className="truncate text-[var(--color-text-dim)]">
                    {conversation.project_name}
                  </span>
                  {conversation.run_status && (
                    <span className={statusTone(conversation.run_status)}>
                      {statusLabel(conversation.run_status)}
                    </span>
                  )}
                </div>
              </button>
              <button
                type="button"
                aria-label="Conversation actions"
                onClick={() =>
                  setMenuId((value) =>
                    value === conversation.id ? null : conversation.id,
                  )
                }
                className="absolute right-2 top-2 rounded-md p-1 text-[var(--color-text-dim)] opacity-0 hover:bg-[var(--color-bg-elevated)] hover:text-[var(--color-text)] group-hover:opacity-100"
              >
                <MoreHorizontal className="h-3.5 w-3.5" />
              </button>
              {menuId === conversation.id && (
                <div className="absolute right-2 top-9 z-20 w-44 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-1 shadow-2xl">
                  {sharingEnabled && (
                    <button
                      type="button"
                      onClick={() => {
                        setMenuId(null);
                        onShare(conversation);
                      }}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                    >
                      <Share2 className="h-3 w-3" />
                      Share with team
                    </button>
                  )}
                  {sharingEnabled && (
                    <button
                      type="button"
                      onClick={() => {
                        setMenuId(null);
                        onRevokeShare(conversation);
                      }}
                      className="w-full rounded-lg px-3 py-2 text-left text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                    >
                      Revoke team link
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      setMenuId(null);
                      onRename(conversation);
                    }}
                    className="w-full rounded-lg px-3 py-2 text-left text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                  >
                    Rename
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMenuId(null);
                      onArchive(conversation);
                    }}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-[var(--color-error)] hover:bg-[var(--color-bg-hover)]"
                  >
                    <Trash2 className="h-3 w-3" />
                    Remove from history
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>
      <div className="border-t border-[var(--color-border)] px-4 py-3 text-[10px] leading-4 text-[var(--color-text-dim)]">
        Private to you · automatically saved
      </div>
    </aside>
  );
}

function QueryApprovalCard({
  event,
  onDecision,
}: {
  event: StandaloneChatEvent;
  onDecision: (
    decision: "approve" | "decline",
    scope?: "run_once" | "current_chat" | "user_defaults",
  ) => Promise<void>;
}) {
  const purpose = eventText(event, "purpose") || "Run the proposed query";
  const estimate = Number(event.payload.estimated_cost_usd ?? 0);
  const remaining = Number(event.payload.remaining_chat_budget_usd ?? 0);
  const quality =
    eventText(event, "estimate_quality") || "estimate unavailable";
  return (
    <section
      role="status"
      aria-live="polite"
      aria-label="Query approval required"
      className="mx-auto mb-2 w-full max-w-3xl rounded-xl border border-[var(--color-warning)]/40 bg-[var(--color-bg-card)] p-4"
    >
      <p className="text-sm font-medium text-[var(--color-text)]">
        Query approval required
      </p>
      <p className="mt-1 text-xs text-[var(--color-text-muted)]">{purpose}</p>
      <div className="mt-3 flex gap-5 text-xs text-[var(--color-text-dim)]">
        <span>Estimated cost: ${estimate.toFixed(4)}</span>
        <span>Remaining chat budget: ${remaining.toFixed(4)}</span>
        <span>Quality: {quality.replaceAll("_", " ")}</span>
      </div>
      <details className="mt-3 text-xs text-[var(--color-text-dim)]">
        <summary>Technical details</summary>
        <code className="mt-2 block break-all">
          SQL hash: {eventText(event, "sql_hash")}
        </code>
      </details>
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void onDecision("approve", "run_once")}
          className="rounded-lg bg-[var(--color-text)] px-3 py-2 text-xs text-[var(--color-bg)]"
        >
          Run once
        </button>
        <button
          type="button"
          onClick={() => void onDecision("approve", "current_chat")}
          className="rounded-lg border border-[var(--color-border)] px-3 py-2 text-xs"
        >
          Increase this chat budgets
        </button>
        <button
          type="button"
          onClick={() => void onDecision("approve", "user_defaults")}
          className="rounded-lg border border-[var(--color-border)] px-3 py-2 text-xs"
        >
          Use as future defaults
        </button>
        <button
          type="button"
          onClick={() => void onDecision("decline")}
          className="rounded-lg px-3 py-2 text-xs text-[var(--color-error)]"
        >
          Decline
        </button>
      </div>
    </section>
  );
}

function ConversationMessagesSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading conversation"
      className="mx-auto flex min-h-full w-full max-w-3xl flex-col justify-end gap-5 px-6 py-10"
    >
      <div className="ml-auto h-12 w-2/5 animate-pulse rounded-2xl bg-[var(--color-bg-card)]" />
      <div className="flex max-w-2xl items-start gap-3">
        <Loader2 className="mt-1 h-4 w-4 flex-none animate-spin text-[var(--color-text-dim)]" />
        <div className="w-full space-y-2">
          <div className="h-3 w-5/6 animate-pulse rounded bg-[var(--color-bg-card)]" />
          <div className="h-3 w-2/3 animate-pulse rounded bg-[var(--color-bg-card)]" />
          <div className="h-3 w-3/4 animate-pulse rounded bg-[var(--color-bg-card)]" />
        </div>
      </div>
      <span className="sr-only">Loading conversation</span>
    </div>
  );
}

export function StandaloneDataChat({
  conversationId,
}: {
  conversationId?: string;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { cache, mutate: mutateCache } = useSWRConfig();
  const { toast } = useToast();
  const {
    data: bootstrap,
    error: bootstrapError,
    isLoading: bootstrapLoading,
  } = useSWR("standalone-chat-bootstrap", getStandaloneChatBootstrap, {
    revalidateOnFocus: false,
  });
  const {
    data: historyData,
    isLoading: historyLoading,
    mutate: mutateHistory,
  } = useSWR("standalone-chat-conversations", listStandaloneConversations, {
    refreshInterval: 4_000,
  });
  const {
    data: detail,
    error: detailError,
    isLoading: detailLoading,
    mutate: mutateDetail,
  } = useSWR(
    conversationId ? `standalone-chat-conversation:${conversationId}` : null,
    () => getStandaloneConversation(conversationId!),
    {
      refreshInterval: (latestDetail) =>
        isStreamingStatus(latestDetail?.current_run?.status) ? 1_000 : 0,
    },
  );
  const requestedProject = searchParams.get("project");
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    null,
  );
  const [perQueryBudgetUsd, setPerQueryBudgetUsd] = useState(0.25);
  const [chatBudgetUsd, setChatBudgetUsd] = useState(1);
  const [draft, setDraft] = useState("");
  const [isConversationRailOpen, setIsConversationRailOpen] = useState(true);
  const [pendingSubmission, setPendingSubmission] =
    useState<OptimisticUserMessage | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [loadingConversationId, setLoadingConversationId] = useState<
    string | null
  >(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const previousConversationIdRef = useRef(conversationId);
  const conversationPrefetches = useRef(
    new Map<string, Promise<StandaloneConversationDetail>>(),
  );
  const selectedInitialized = useRef(false);

  useEffect(() => {
    if (!bootstrap || selectedInitialized.current) return;
    const requested = bootstrap.projects.find(
      (project) => project.id === requestedProject,
    );
    setSelectedProjectId(
      requested?.id ??
        bootstrap.selected_project_id ??
        bootstrap.projects[0]?.id ??
        null,
    );
    setPerQueryBudgetUsd(bootstrap.default_per_query_budget_usd);
    setChatBudgetUsd(bootstrap.default_chat_budget_usd);
    selectedInitialized.current = true;
  }, [bootstrap, requestedProject]);

  useEffect(() => {
    if (detail?.conversation.project_id) {
      setSelectedProjectId(detail.conversation.project_id);
      selectedInitialized.current = true;
    }
  }, [detail?.conversation.project_id]);

  const { data: readiness } = useSWR(
    selectedProjectId ? `standalone-chat-readiness:${selectedProjectId}` : null,
    () => getStandaloneChatProjectReadiness(selectedProjectId!),
    { revalidateOnFocus: false },
  );

  const currentRun = detail?.current_run ?? null;
  const events = detail?.run_events ?? [];
  const eventsRef = useRef(events);
  useEffect(() => {
    eventsRef.current = events;
  }, [events]);
  const conversationLoading = Boolean(
    conversationId && !detail && !detailError && detailLoading,
  );
  const approvalEvent = useMemo(() => {
    if (currentRun?.status !== "waiting_for_query_approval") return null;
    const decisions = new Set(
      events
        .filter(
          (event) =>
            event.type === "query_approved" || event.type === "query_declined",
        )
        .map((event) => eventText(event, "proposal_id")),
    );
    return (
      [...events]
        .reverse()
        .find(
          (event) =>
            event.run_id === currentRun.id &&
            event.type === "query_approval_requested" &&
            !decisions.has(eventText(event, "proposal_id")),
        ) ?? null
    );
  }, [currentRun, events]);
  const onQueryDecision = useCallback(
    async (
      decision: "approve" | "decline",
      scope: "run_once" | "current_chat" | "user_defaults" = "run_once",
    ) => {
      if (!approvalEvent || !detail) return;
      const estimate = Number(approvalEvent.payload.estimated_cost_usd ?? 0);
      const proposalId = eventText(approvalEvent, "proposal_id");
      const budgets =
        scope === "run_once"
          ? undefined
          : {
              perQueryBudgetUsd: Math.max(
                detail.conversation.per_query_budget_usd,
                estimate,
              ),
              chatBudgetUsd: Math.max(
                detail.conversation.chat_budget_usd,
                detail.conversation.actual_spend_usd + estimate,
                estimate,
              ),
            };
      try {
        await decideStandaloneQueryProposal(
          proposalId,
          decision,
          scope,
          budgets,
        );
        await mutateDetail();
        await mutateHistory();
      } catch (error) {
        toast(
          error instanceof Error
            ? error.message
            : "Could not save the query decision",
          "error",
        );
      }
    },
    [approvalEvent, detail, mutateDetail, mutateHistory, toast],
  );
  const currentRunId = currentRun?.id;
  const streamStatus = currentRun?.status;
  useEffect(() => {
    if (!currentRunId) {
      return;
    }
    const controller = new AbortController();
    const currentEvents = eventsRef.current.filter(
      (event) => event.run_id === currentRunId,
    );
    const after = currentEvents.reduce(
      (maximum, event) => Math.max(maximum, event.sequence),
      0,
    );
    let cursor = after;
    let retryDelay = 250;
    const followRun = async () => {
      while (!controller.signal.aborted) {
        try {
          await streamStandaloneRunEvents(
            currentRunId,
            cursor,
            controller.signal,
            (event) => {
              cursor = Math.max(cursor, event.sequence);
              void mutateDetail(
                (current) =>
                  current ? applyStandaloneChatEvent(current, event) : current,
                { revalidate: false },
              );
              if (event.type === "status") {
                const status = event.payload.status;
                if (typeof status === "string") {
                  void mutateHistory(
                    (current) =>
                      current
                        ? {
                            conversations: current.conversations.map(
                              (conversation) =>
                                conversation.id === conversationId
                                  ? {
                                      ...conversation,
                                      run_status:
                                        status as StandaloneChatRunStatus,
                                    }
                                  : conversation,
                            ),
                          }
                        : current,
                    { revalidate: false },
                  );
                }
              }
            },
          );
        } catch (error) {
          if (controller.signal.aborted) return;
          if (error instanceof DOMException && error.name === "AbortError") {
            return;
          }
        }
        if (controller.signal.aborted) return;
        try {
          const latest = await mutateDetail();
          void mutateHistory();
          if (latest && isStandaloneRunReconciled(latest, currentRunId)) {
            return;
          }
        } catch {
          // The next bounded retry reconciles transient network failures.
        }
        await new Promise((resolve) => window.setTimeout(resolve, retryDelay));
        retryDelay = Math.min(retryDelay * 2, 5_000);
      }
    };
    void followRun();
    return () => controller.abort();
  }, [conversationId, currentRunId, streamStatus, mutateDetail, mutateHistory]);

  const uiMessages = useMemo<UiMessage[]>(() => {
    const messages: UiMessage[] = [...(detail?.messages ?? [])];
    if (currentRun) {
      const runMessages = messages.filter(
        (message) => message.metadata.run_id === currentRun.id,
      );
      const hasTerminalMessage = runMessages.some(
        (message) =>
          message.role === "assistant" &&
          ["completed", "failed", "cancelled"].includes(
            typeof message.metadata.status === "string"
              ? message.metadata.status
              : "",
          ),
      );
      const hasWaitingMessage = runMessages.some(
        (message) =>
          message.role === "assistant" &&
          message.metadata.status === "waiting_for_user",
      );
      if (
        !hasTerminalMessage &&
        !(currentRun.status === "waiting_for_user" && hasWaitingMessage)
      ) {
        const runEvents = events.filter(
          (event) => event.run_id === currentRun.id,
        );
        const resetSequence = runEvents.reduce(
          (latest, event) =>
            event.type === "status" && event.payload?.reset_text === true
              ? Math.max(latest, event.sequence)
              : latest,
          0,
        );
        const streamed = assembleStandaloneRunText(
          runEvents,
          currentRun.id,
          resetSequence,
        );
        const clarification = [...runEvents]
          .reverse()
          .find((event) => event.type === "clarification_requested");
        const error = [...runEvents]
          .reverse()
          .find((event) => event.type === "error");
        const progress = [...runEvents]
          .reverse()
          .find((event) => event.type === "progress");
        const content =
          (clarification && eventText(clarification, "message")) ||
          streamed ||
          (error && eventText(error, "message")) ||
          (currentRun.status === "cancelled"
            ? "This run was stopped."
            : eventText(progress, "label") || "Preparing your answer…");
        messages.push({
          id: `run-${currentRun.id}`,
          role: "assistant",
          content,
          sequence: Number.MAX_SAFE_INTEGER,
          created_at: Date.parse(currentRun.created_at) / 1_000,
          metadata: { run_id: currentRun.id, optimistic: true },
          runId: currentRun.id,
          runStatus: currentRun.status,
          synthetic: true,
        });
      }
    }
    if (
      pendingSubmission &&
      !containsStandaloneSubmission(messages, pendingSubmission)
    ) {
      messages.push({
        id: pendingSubmission.id,
        role: "user",
        content: pendingSubmission.content,
        sequence: Number.MAX_SAFE_INTEGER - 1,
        created_at: pendingSubmission.createdAt,
        metadata: { optimistic: true },
      });
    }
    if (
      pendingSubmission &&
      isSubmitting &&
      !isStreamingStatus(currentRun?.status)
    ) {
      messages.push({
        id: `pending-assistant-${pendingSubmission.id}`,
        role: "assistant",
        content: "Preparing your answer…",
        sequence: Number.MAX_SAFE_INTEGER,
        created_at: pendingSubmission.createdAt,
        metadata: { optimistic: true },
        runStatus: "queued",
        synthetic: true,
      });
    }
    return messages;
  }, [currentRun, detail?.messages, events, isSubmitting, pendingSubmission]);

  useEffect(() => {
    if (
      pendingSubmission &&
      containsStandaloneSubmission(
        detail?.messages ?? [],
        pendingSubmission,
        true,
      )
    ) {
      setPendingSubmission(null);
    }
  }, [detail?.messages, pendingSubmission]);

  const submitText = useCallback(
    async (text: string) => {
      text = text.trim();
      if (!text || isSubmitting) return;
      shouldStickToBottomRef.current = true;
      const optimistic: OptimisticUserMessage = {
        id: `optimistic-${crypto.randomUUID()}`,
        content: text,
        createdAt: Date.now() / 1_000,
      };
      setPendingSubmission(optimistic);
      setIsSubmitting(true);
      try {
        if (!conversationId) {
          if (!selectedProjectId) throw new Error("Select a project first");
          const created = await createStandaloneConversation(
            selectedProjectId,
            text,
            perQueryBudgetUsd,
            chatBudgetUsd,
          );
          await mutateCache(
            `standalone-chat-conversation:${created.conversation.id}`,
            created,
            { revalidate: false },
          );
          await mutateHistory(
            (current) => ({
              conversations: upsertStandaloneConversation(
                current?.conversations ?? [],
                created.conversation,
              ),
            }),
            { revalidate: false },
          );
          router.replace(`/chats/${created.conversation.id}`);
          void mutateHistory();
          return;
        }
        await mutateDetail(
          (current) =>
            current
              ? appendOptimisticUserMessage(current, optimistic)
              : current,
          { revalidate: false },
        );
        let run;
        if (currentRun?.status === "waiting_for_user") {
          run = await clarifyStandaloneRun(currentRun.id, text);
        } else {
          run = await createStandaloneRun(conversationId, text);
        }
        await mutateDetail(
          (current) =>
            current
              ? {
                  ...current,
                  conversation: {
                    ...current.conversation,
                    run_status: run.status,
                    updated_at: Date.now() / 1_000,
                  },
                  messages: current.messages.map((message) =>
                    message.id === optimistic.id
                      ? {
                          ...message,
                          metadata: {
                            ...message.metadata,
                            run_id: run.id,
                          },
                        }
                      : message,
                  ),
                  current_run: run,
                }
              : current,
          { revalidate: false },
        );
        await mutateHistory(
          (current) =>
            current
              ? {
                  conversations: current.conversations.map((conversation) =>
                    conversation.id === conversationId
                      ? {
                          ...conversation,
                          run_status: run.status,
                          updated_at: Date.now() / 1_000,
                        }
                      : conversation,
                  ),
                }
              : current,
          { revalidate: false },
        );
        setPendingSubmission(null);
        void mutateDetail();
        void mutateHistory();
      } catch (error) {
        if (conversationId) {
          await mutateDetail(
            (current) =>
              current
                ? {
                    ...current,
                    messages: current.messages.filter(
                      (message) => message.id !== optimistic.id,
                    ),
                  }
                : current,
            { revalidate: false },
          );
        }
        setPendingSubmission(null);
        setDraft(text);
        toast(
          error instanceof Error ? error.message : "Could not send message",
          "error",
        );
      } finally {
        setIsSubmitting(false);
      }
    },
    [
      conversationId,
      currentRun,
      isSubmitting,
      mutateDetail,
      mutateCache,
      mutateHistory,
      router,
      selectedProjectId,
      perQueryBudgetUsd,
      chatBudgetUsd,
      toast,
    ],
  );

  const onStop = useCallback(
    async (runId: string) => {
      try {
        await cancelStandaloneRun(runId);
        await mutateDetail();
        await mutateHistory();
      } catch (error) {
        toast(
          error instanceof Error ? error.message : "Could not stop the run",
          "error",
        );
      }
    },
    [mutateDetail, mutateHistory, toast],
  );
  const onRetry = useCallback(
    async (runId: string) => {
      try {
        const run = await retryStandaloneRun(runId);
        await mutateDetail(
          (current) =>
            current
              ? {
                  ...current,
                  current_run: run,
                }
              : current,
          { revalidate: false },
        );
        void mutateDetail();
        await mutateHistory();
      } catch (error) {
        toast(
          error instanceof Error ? error.message : "Could not retry the run",
          "error",
        );
      }
    },
    [mutateDetail, mutateHistory, toast],
  );

  const loadConversation = useCallback(
    (id: string): Promise<StandaloneConversationDetail> => {
      const key = `standalone-chat-conversation:${id}`;
      const cached = cache.get(key) as
        { data?: StandaloneConversationDetail } | undefined;
      if (cached?.data) return Promise.resolve(cached.data);
      const existing = conversationPrefetches.current.get(id);
      if (existing) return existing;
      const request = getStandaloneConversation(id)
        .then(async (conversation) => {
          await mutateCache(key, conversation, { revalidate: false });
          return conversation;
        })
        .finally(() => conversationPrefetches.current.delete(id));
      conversationPrefetches.current.set(id, request);
      return request;
    },
    [cache, mutateCache],
  );
  const prefetchConversation = useCallback(
    (id: string) => {
      router.prefetch(`/chats/${id}`);
      void loadConversation(id).catch(() => undefined);
    },
    [loadConversation, router],
  );
  const selectConversation = useCallback(
    async (id: string) => {
      if (id === conversationId) return;
      shouldStickToBottomRef.current = true;
      setLoadingConversationId(id);
      router.prefetch(`/chats/${id}`);
      try {
        await loadConversation(id);
        router.push(`/chats/${id}`);
      } catch (error) {
        toast(
          error instanceof Error
            ? error.message
            : "Could not load the conversation",
          "error",
        );
      } finally {
        setLoadingConversationId(null);
      }
    },
    [conversationId, loadConversation, router, toast],
  );

  const submitDisabled =
    isSubmitting ||
    conversationLoading ||
    !selectedProjectId ||
    (readiness?.ready === false && currentRun?.status !== "waiting_for_user") ||
    currentRun?.status === "queued" ||
    currentRun?.status === "running" ||
    currentRun?.status === "waiting_for_query_approval";

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    const switchedConversation =
      previousConversationIdRef.current !== conversationId;
    previousConversationIdRef.current = conversationId;
    if (switchedConversation) shouldStickToBottomRef.current = true;
    if (!viewport || !shouldStickToBottomRef.current) return;
    viewport.scrollTop = viewport.scrollHeight;
  }, [conversationId, uiMessages]);

  const onViewportScroll = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const distanceFromBottom =
      viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    shouldStickToBottomRef.current = distanceFromBottom < 96;
  }, []);

  const conversations = historyData?.conversations ?? [];
  const starters =
    readiness?.starter_questions ??
    (selectedProjectId === bootstrap?.selected_project_id
      ? bootstrap?.starter_questions
      : []) ??
    [];
  const empty = uiMessages.length === 0;
  const noProjects = bootstrap?.projects.length === 0;
  const unreadyMessage = noProjects
    ? bootstrap?.is_admin
      ? "No accessible project is ready. Set up a project and production connection to begin."
      : "No project is ready for data chat. Ask an administrator to finish setup."
    : readiness?.ready === false
      ? readiness.setup_cta
        ? `${readiness.message} Open project or connection settings to finish setup.`
        : readiness.message
      : null;
  const showSetupCta =
    bootstrap?.is_admin === true &&
    (noProjects || readiness?.setup_cta === true);

  const renameConversation = async (conversation: StandaloneConversation) => {
    const title = window
      .prompt("Rename conversation", conversation.title)
      ?.trim();
    if (!title || title === conversation.title) return;
    try {
      await renameStandaloneConversation(conversation.id, title);
      await mutateHistory();
      if (conversation.id === conversationId) await mutateDetail();
    } catch (error) {
      toast(
        error instanceof Error ? error.message : "Could not rename the chat",
        "error",
      );
    }
  };
  const archiveConversation = async (conversation: StandaloneConversation) => {
    if (
      !window.confirm(
        "Remove this conversation from history? This cannot be undone.",
      )
    ) {
      return;
    }
    try {
      await archiveStandaloneConversation(conversation.id);
      await mutateHistory();
      if (conversation.id === conversationId) router.push("/chats");
    } catch (error) {
      toast(
        error instanceof Error ? error.message : "Could not remove the chat",
        "error",
      );
    }
  };
  const shareConversation = async (conversation: StandaloneConversation) => {
    try {
      const grant = await shareStandaloneConversation(conversation.id);
      const url = `${window.location.origin}/chats/shared/${grant.token}`;
      try {
        await navigator.clipboard.writeText(url);
        toast("Team link copied", "success");
      } catch {
        window.prompt("Copy team link", url);
      }
    } catch (error) {
      toast(
        error instanceof Error ? error.message : "Could not share the chat",
        "error",
      );
    }
  };
  const revokeShare = async (conversation: StandaloneConversation) => {
    if (!window.confirm("Revoke all active team links for this chat?")) return;
    try {
      await revokeStandaloneConversationShare(conversation.id);
      toast("Team link revoked", "success");
    } catch (error) {
      toast(
        error instanceof Error ? error.message : "Could not revoke the link",
        "error",
      );
    }
  };

  if (bootstrapLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
      </div>
    );
  }
  if (bootstrapError || !bootstrap?.enabled) {
    return (
      <div className="flex h-screen items-center justify-center p-8">
        <div className="max-w-md rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6 text-center">
          <AlertCircle className="mx-auto mb-3 h-5 w-5 text-[var(--color-text-dim)]" />
          <h1 className="text-base text-[var(--color-text)]">
            Data chat is unavailable
          </h1>
          <p className="mt-2 text-sm text-[var(--color-text-muted)]">
            Ask an administrator to enable standalone data chat.
          </p>
        </div>
      </div>
    );
  }
  if (detailError) {
    return (
      <div className="flex h-screen items-center justify-center p-8">
        <div className="max-w-md rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6 text-center">
          <AlertCircle className="mx-auto mb-3 h-5 w-5 text-[var(--color-error)]" />
          <h1 className="text-base text-[var(--color-text)]">
            Conversation not found
          </h1>
          <p className="mt-2 text-sm text-[var(--color-text-muted)]">
            This conversation does not exist or is not available to your
            account.
          </p>
          <button
            type="button"
            onClick={() => router.push("/chats")}
            className="mt-4 rounded-lg border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text)]"
          >
            Start a new chat
          </button>
        </div>
      </div>
    );
  }

  return (
    <ChatUiContext.Provider
      value={{
        events,
        artifacts: detail?.artifacts ?? [],
        onStop,
        onRetry,
      }}
    >
      <div className="h-screen min-w-[960px] overflow-hidden p-4">
        <div className="relative flex h-full overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg)] shadow-2xl shadow-black/20">
          <button
            type="button"
            aria-label={
              isConversationRailOpen
                ? "Collapse chat history"
                : "Expand chat history"
            }
            aria-expanded={isConversationRailOpen}
            onClick={() => setIsConversationRailOpen((isOpen) => !isOpen)}
            className={`absolute top-3 z-30 flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-dim)] shadow-lg shadow-black/20 transition-[left,color,background-color] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] ${
              isConversationRailOpen ? "left-[17rem]" : "left-3"
            }`}
          >
            <PanelLeft className="h-4 w-4" />
          </button>
          {isConversationRailOpen && (
            <ConversationRail
              conversations={conversations}
              activeId={conversationId}
              historyLoading={historyLoading}
              loadingConversationId={loadingConversationId}
              onNewConversation={() => router.push("/chats")}
              onSelectConversation={(id) => void selectConversation(id)}
              onPrefetchConversation={prefetchConversation}
              onRename={(conversation) => void renameConversation(conversation)}
              onArchive={(conversation) =>
                void archiveConversation(conversation)
              }
              onShare={(conversation) => void shareConversation(conversation)}
              onRevokeShare={(conversation) => void revokeShare(conversation)}
              sharingEnabled={Boolean(
                bootstrap.enterprise_features.organization_sharing,
              )}
            />
          )}
          <main className="relative flex min-w-0 flex-1 flex-col">
            {conversationId &&
              detail &&
              bootstrap.enterprise_features.organization_sharing && (
                <button
                  type="button"
                  aria-label="Share conversation"
                  title="Create a new authenticated team link and revoke any previous link"
                  onClick={() => void shareConversation(detail.conversation)}
                  className="absolute right-4 top-4 z-20 flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-muted)] shadow-lg shadow-black/20 hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                >
                  <Share2 className="h-4 w-4" />
                </button>
              )}
            {conversationId && unreadyMessage && (
              <div className="flex-none px-6 pt-4">
                <ReadinessNotice
                  message={unreadyMessage}
                  showSetup={showSetupCta}
                  onSetup={() => router.push("/projects")}
                />
              </div>
            )}
            <div
              ref={viewportRef}
              onScroll={onViewportScroll}
              className="min-h-0 flex-1 overflow-y-auto"
            >
              {conversationLoading ? (
                <ConversationMessagesSkeleton />
              ) : empty ? (
                <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-6 py-12">
                  <div className="mb-8">
                    <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]">
                      <Sparkles className="h-4 w-4 text-[var(--color-success)]" />
                    </div>
                    <h1 className="text-2xl font-medium tracking-[-0.025em] text-[var(--color-text)]">
                      What would you like to understand?
                    </h1>
                    <p className="mt-2 max-w-xl text-sm leading-6 text-[var(--color-text-muted)]">
                      Ask in plain English. SignalPilot will inspect the
                      project, query governed production data, and choose the
                      clearest answer format.
                    </p>
                  </div>
                  {unreadyMessage ? (
                    <ReadinessNotice
                      message={unreadyMessage}
                      showSetup={showSetupCta}
                      onSetup={() => router.push("/projects")}
                    />
                  ) : starters.length === 4 ? (
                    <StarterQuestions
                      questions={starters}
                      onSelect={setDraft}
                    />
                  ) : (
                    <div className="grid grid-cols-2 gap-3">
                      {[0, 1, 2, 3].map((index) => (
                        <div
                          key={index}
                          className="h-24 animate-pulse rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]"
                        />
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div data-testid="standalone-chat-messages">
                  {uiMessages.map((message) => (
                    <ChatMessage
                      key={standaloneMessageKey(conversationId, message)}
                      message={message}
                    />
                  ))}
                </div>
              )}
              <div className="sticky bottom-0 bg-gradient-to-t from-[var(--color-bg)] via-[var(--color-bg)] to-transparent pt-3">
                {approvalEvent && (
                  <QueryApprovalCard
                    event={approvalEvent}
                    onDecision={onQueryDecision}
                  />
                )}
                <StandaloneChatComposer
                  value={draft}
                  onValueChange={setDraft}
                  onSubmit={(text) => void submitText(text)}
                  submitDisabled={submitDisabled}
                  placeholder={
                    currentRun?.status === "waiting_for_user"
                      ? "Answer the clarification…"
                      : currentRun?.status === "waiting_for_query_approval"
                        ? "Approve or decline the proposed query above…"
                        : "Ask a question about this project…"
                  }
                  projectPicker={
                    !conversationId ? (
                      <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--color-text-dim)]">
                        <label className="flex items-center gap-2">
                          <span>Project</span>
                          <select
                            value={selectedProjectId ?? ""}
                            onChange={(event) => {
                              const projectId = event.target.value;
                              setSelectedProjectId(projectId);
                              void setDefaultStandaloneChatProject(projectId);
                              router.replace(
                                `/chats?project=${encodeURIComponent(projectId)}`,
                              );
                            }}
                            aria-label="Select project"
                            className="rounded-full border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-1.5 text-xs text-[var(--color-text-muted)] focus:outline-none"
                          >
                            {bootstrap.projects.map((project) => (
                              <option key={project.id} value={project.id}>
                                {project.display_name}
                                {project.ready
                                  ? ""
                                  : projectSetupSuffix(
                                      project.readiness_message,
                                    )}
                              </option>
                            ))}
                          </select>
                        </label>
                        {bootstrap.enterprise_features.query_approval && (
                          <>
                            <label className="flex items-center gap-2">
                              <span>Per-query budget</span>
                              <input
                                type="number"
                                min="0"
                                step="0.01"
                                value={perQueryBudgetUsd}
                                onChange={(event) =>
                                  setPerQueryBudgetUsd(
                                    Math.max(0, Number(event.target.value)),
                                  )
                                }
                                aria-label="Per-query budget in USD"
                                className="w-20 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-1.5"
                              />
                            </label>
                            <label className="flex items-center gap-2">
                              <span>Chat budget</span>
                              <input
                                type="number"
                                min={perQueryBudgetUsd}
                                step="0.01"
                                value={chatBudgetUsd}
                                onChange={(event) =>
                                  setChatBudgetUsd(
                                    Math.max(
                                      perQueryBudgetUsd,
                                      Number(event.target.value),
                                    ),
                                  )
                                }
                                aria-label="Chat budget in USD"
                                className="w-20 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-1.5"
                              />
                            </label>
                          </>
                        )}
                      </div>
                    ) : undefined
                  }
                />
              </div>
            </div>
          </main>
        </div>
      </div>
    </ChatUiContext.Provider>
  );
}
