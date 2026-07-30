"use client";

import {
  ActionBarPrimitive,
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePartPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAui,
  useAuiState,
  useExternalStoreRuntime,
  useMessagePartText,
  type AppendMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";
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
  Send,
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
  downloadStandaloneArtifact,
  getStandaloneChatBootstrap,
  getStandaloneChatProjectReadiness,
  getStandaloneConversation,
  listStandaloneConversations,
  renameStandaloneConversation,
  retryStandaloneRun,
  setDefaultStandaloneChatProject,
  streamStandaloneRunEvents,
  type StandaloneChatArtifact,
  type StandaloneChatEvent,
  type StandaloneChatMessage,
  type StandaloneChatRunStatus,
  type StandaloneConversation,
  type StandaloneConversationDetail,
} from "~/lib/api";
import { useToast } from "~/components/ui/toast";

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
    completed: "Completed",
    failed: "Failed",
    cancelled: "Stopped",
  }[status];
}

function statusTone(status: StandaloneChatRunStatus | null): string {
  if (status === "running" || status === "queued")
    return "text-[var(--color-success)]";
  if (status === "waiting_for_user") return "text-[var(--color-warning)]";
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

function extractText(message: AppendMessage): string {
  return message.content
    .filter((part) => part.type === "text")
    .map((part) => ("text" in part ? part.text : ""))
    .join("\n")
    .trim();
}

function mergeEvents(
  current: StandaloneChatEvent[],
  incoming: StandaloneChatEvent[],
): StandaloneChatEvent[] {
  const byId = new Map(
    current.map((event) => [`${event.run_id}:${event.sequence}`, event]),
  );
  for (const event of incoming) {
    byId.set(`${event.run_id}:${event.sequence}`, event);
  }
  return [...byId.values()].sort((a, b) => {
    const timestamp = Date.parse(a.created_at) - Date.parse(b.created_at);
    return timestamp || a.sequence - b.sequence;
  });
}

function eventText(
  event: StandaloneChatEvent | null | undefined,
  key: string,
): string {
  const value = event?.payload?.[key];
  return typeof value === "string" ? value : "";
}

function MarkdownText() {
  const { text } = useMessagePartText();
  return (
    <div className="chat-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

function PlainText() {
  return (
    <MessagePartPrimitive.Text
      component="div"
      smooth={false}
      className="whitespace-pre-wrap"
    />
  );
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

function ArtifactDownloads({ artifact }: { artifact: StandaloneChatArtifact }) {
  const { toast } = useToast();
  return (
    <div className="flex flex-wrap items-center gap-2">
      {artifact.download_formats.map((format) => (
        <button
          key={format}
          type="button"
          onClick={() =>
            downloadStandaloneArtifact(
              artifact.id,
              format,
              artifact.filename,
            ).catch(() => toast("Download failed", "error"))
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

function ArtifactContext({ artifact }: { artifact: StandaloneChatArtifact }) {
  const notes = [
    ...artifact.assumptions.map((value) => `Assumption: ${value}`),
    ...artifact.exclusions.map((value) => `Exclusion: ${value}`),
    ...artifact.caveats.map((value) => `Caveat: ${value}`),
  ];
  if (!artifact.freshness_at && notes.length === 0) return null;
  return (
    <div className="border-t border-[var(--color-border)] px-3 py-2 text-[11px] leading-5 text-[var(--color-text-dim)]">
      {artifact.freshness_at && (
        <p>Fresh through {new Date(artifact.freshness_at).toLocaleString()}.</p>
      )}
      {notes.map((note) => (
        <p key={note}>{note}</p>
      ))}
    </div>
  );
}

function ArtifactPreview({ artifact }: { artifact: StandaloneChatArtifact }) {
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
            <ArtifactDownloads artifact={artifact} />
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
        <ArtifactContext artifact={artifact} />
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
    const displayLimited =
      "limited" in display && display.limited === true;
    const categoryLimit =
      "category_limit" in display &&
      typeof display.category_limit === "number"
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
          <ArtifactDownloads artifact={artifact} />
        </div>
        <div className="min-h-64 overflow-x-auto p-4">
          <div className="mx-auto w-fit min-w-[640px]">
            <VegaEmbed
              spec={spec}
              options={{ actions: false, mode: "vega-lite", renderer: "svg" }}
            />
          </div>
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
        <ArtifactContext artifact={artifact} />
      </div>
    );
  }
  const html = typeof snapshot.html === "string" ? snapshot.html : "";
  const reportBody = /<body(?:\s[^>]*)?>([\s\S]*?)<\/body>/i.exec(html)?.[1] ?? html;
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
        <ArtifactDownloads artifact={artifact} />
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
      <ArtifactContext artifact={artifact} />
    </div>
  );
}

function AssistantMessage() {
  const custom = useAuiState((state) => state.message.metadata.custom) as
    Record<string, unknown> | undefined;
  const runId = typeof custom?.runId === "string" ? custom.runId : "";
  const runStatus =
    typeof custom?.runStatus === "string"
      ? (custom.runStatus as StandaloneChatRunStatus)
      : "completed";
  const [showWork, setShowWork] = useState(false);
  const { artifacts, onRetry, onStop } = useChatUi();
  const messageId = useAuiState((state) => state.message.id);
  const attachedArtifacts = artifacts.filter(
    (artifact) =>
      artifact.assistant_message_id === messageId ||
      (!artifact.assistant_message_id && artifact.run_id === runId),
  );
  const successful = runStatus === "completed";
  const running = runStatus === "queued" || runStatus === "running";
  return (
    <MessagePrimitive.Root className="group mx-auto w-full max-w-3xl px-6 py-5">
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
          <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
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
              <ActionBarPrimitive.Root>
                <ActionBarPrimitive.Copy className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]">
                  <Copy className="h-3 w-3" />
                  Copy
                </ActionBarPrimitive.Copy>
              </ActionBarPrimitive.Root>
            )}
            {runId && (
              <button
                type="button"
                onClick={() => setShowWork((value) => !value)}
                className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
              >
                <Wrench className="h-3 w-3" />
                View work
                <ChevronRight
                  className={`h-3 w-3 transition-transform ${showWork ? "rotate-90" : ""}`}
                />
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
          {showWork && runId && (
            <div className="mt-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
              <WorkTimeline runId={runId} />
            </div>
          )}
        </div>
      </div>
    </MessagePrimitive.Root>
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="mx-auto w-full max-w-3xl px-6 py-4">
      <div className="ml-auto max-w-[78%] rounded-2xl rounded-br-md border border-[var(--color-border)] bg-[var(--color-bg-elevated)] px-4 py-3 text-sm leading-6 text-[var(--color-text)]">
        <MessagePrimitive.Parts components={{ Text: PlainText }} />
      </div>
    </MessagePrimitive.Root>
  );
}

function ChatMessage() {
  return (
    <>
      <MessagePrimitive.If user>
        <UserMessage />
      </MessagePrimitive.If>
      <MessagePrimitive.If assistant>
        <AssistantMessage />
      </MessagePrimitive.If>
    </>
  );
}

function StarterQuestions({ questions }: { questions: string[] }) {
  const aui = useAui();
  return (
    <div className="grid grid-cols-2 gap-3">
      {questions.slice(0, 4).map((question) => (
        <button
          key={question}
          type="button"
          onClick={() => {
            aui.composer.setText(question);
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
  onRename,
  onArchive,
}: {
  conversations: StandaloneConversation[];
  activeId?: string;
  onRename: (conversation: StandaloneConversation) => void;
  onArchive: (conversation: StandaloneConversation) => void;
}) {
  const router = useRouter();
  const [menuId, setMenuId] = useState<string | null>(null);
  return (
    <aside className="flex w-72 flex-none flex-col border-r border-[var(--color-border)] bg-[var(--color-sidebar)]">
      <div className="p-3">
        <button
          type="button"
          onClick={() => router.push("/chats")}
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
        {conversations.length === 0 ? (
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
                onClick={() => router.push(`/chats/${conversation.id}`)}
                className="w-full px-3 py-2.5 pr-9 text-left"
              >
                <div className="truncate text-[13px] text-[var(--color-text)]">
                  {conversation.title}
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

function Composer({ placeholder }: { placeholder: string }) {
  const canSend = useAuiState((state) => state.composer.canSend);
  return (
    <div className="mx-auto w-full max-w-3xl px-6 pb-6 pt-3">
      <ComposerPrimitive.Root className="relative overflow-hidden rounded-2xl border border-[var(--color-border-hover)] bg-[var(--color-bg-input)] shadow-2xl shadow-black/20 transition-colors focus-within:border-[var(--color-border-active)]">
        <ComposerPrimitive.Input
          data-chat-composer
          rows={1}
          autoFocus
          placeholder={placeholder}
          className="max-h-48 min-h-14 w-full resize-none border-0 bg-transparent px-4 py-4 pr-14 text-sm leading-6 text-[var(--color-text)] shadow-none outline-none placeholder:text-[var(--color-text-dim)] focus:border-0 focus:shadow-none focus:outline-none focus-visible:outline-none focus-visible:ring-0"
        />
        <ComposerPrimitive.Send
          disabled={!canSend}
          aria-label="Send message"
          className="absolute bottom-3 right-3 flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-text)] text-[var(--color-bg)] disabled:cursor-not-allowed disabled:opacity-30"
        >
          <Send className="h-3.5 w-3.5" />
        </ComposerPrimitive.Send>
      </ComposerPrimitive.Root>
      <p className="mt-2 text-center text-[10px] text-[var(--color-text-dim)]">
        Answers use governed, read-only access. Check freshness and caveats.
      </p>
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
  const { mutate: mutateCache } = useSWRConfig();
  const { toast } = useToast();
  const {
    data: bootstrap,
    error: bootstrapError,
    isLoading: bootstrapLoading,
  } = useSWR("standalone-chat-bootstrap", getStandaloneChatBootstrap, {
    revalidateOnFocus: false,
  });
  const { data: historyData, mutate: mutateHistory } = useSWR(
    "standalone-chat-conversations",
    listStandaloneConversations,
    { refreshInterval: 4_000 },
  );
  const {
    data: detail,
    error: detailError,
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
  const [events, setEvents] = useState<StandaloneChatEvent[]>([]);
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
    selectedInitialized.current = true;
  }, [bootstrap, requestedProject]);

  useEffect(() => {
    if (detail?.conversation.project_id) {
      setSelectedProjectId(detail.conversation.project_id);
      selectedInitialized.current = true;
    }
  }, [detail?.conversation.project_id]);

  useEffect(() => {
    setEvents([]);
  }, [conversationId]);

  useEffect(() => {
    if (detail?.run_events) {
      setEvents((current) => mergeEvents(current, detail.run_events));
    }
  }, [detail?.run_events]);

  const { data: readiness } = useSWR(
    selectedProjectId ? `standalone-chat-readiness:${selectedProjectId}` : null,
    () => getStandaloneChatProjectReadiness(selectedProjectId!),
    { revalidateOnFocus: false },
  );

  const currentRun = detail?.current_run ?? null;
  const streamStatus = currentRun?.status;
  useEffect(() => {
    if (!currentRun || !isStreamingStatus(currentRun.status)) {
      return;
    }
    const controller = new AbortController();
    const currentEvents = events.filter(
      (event) => event.run_id === currentRun.id,
    );
    const after = currentEvents.reduce(
      (maximum, event) => Math.max(maximum, event.sequence),
      0,
    );
    streamStandaloneRunEvents(
      currentRun.id,
      after,
      controller.signal,
      (event) => {
        setEvents((value) => mergeEvents(value, [event]));
        if (
          event.type === "status" ||
          event.type === "artifact_created" ||
          event.type === "clarification_requested"
        ) {
          void mutateDetail();
          void mutateHistory();
        }
      },
    )
      .then(() => {
        void mutateDetail();
        void mutateHistory();
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError")
          return;
        window.setTimeout(() => void mutateDetail(), 1_000);
      });
    return () => controller.abort();
    // `events` intentionally does not restart the stream for every received event.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentRun?.id, streamStatus, mutateDetail, mutateHistory]);

  const uiMessages = useMemo<UiMessage[]>(() => {
    const messages: UiMessage[] = [...(detail?.messages ?? [])];
    if (!currentRun) return messages;
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
      hasTerminalMessage ||
      (currentRun.status === "waiting_for_user" && hasWaitingMessage)
    ) {
      return messages;
    }
    const runEvents = events.filter((event) => event.run_id === currentRun.id);
    const resetSequence = runEvents.reduce(
      (latest, event) =>
        event.type === "status" && event.payload?.reset_text === true
          ? Math.max(latest, event.sequence)
          : latest,
      0,
    );
    const streamed = runEvents
      .filter(
        (event) =>
          event.type === "text_delta" && event.sequence > resetSequence,
      )
      .map((event) => eventText(event, "delta"))
      .join("");
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
        : eventText(progress, "label") ||
          "Preparing your answer…");
    messages.push({
      id: `run-${currentRun.id}`,
      role: "assistant",
      content,
      sequence: Number.MAX_SAFE_INTEGER,
      created_at: Date.parse(currentRun.created_at) / 1_000,
      metadata: { run_id: currentRun.id },
      runId: currentRun.id,
      runStatus: currentRun.status,
      synthetic: true,
    });
    return messages;
  }, [currentRun, detail?.messages, events]);

  const submitMessage = useCallback(
    async (appendMessage: AppendMessage) => {
      const text = extractText(appendMessage);
      if (!text) return;
      try {
        if (!conversationId) {
          if (!selectedProjectId) throw new Error("Select a project first");
          const created = await createStandaloneConversation(
            selectedProjectId,
            text,
          );
          await mutateCache(
            `standalone-chat-conversation:${created.conversation.id}`,
            created,
            { revalidate: false },
          );
          await mutateHistory();
          router.replace(`/chats/${created.conversation.id}`);
          return;
        }
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
                  current_run: run,
                }
              : current,
          { revalidate: false },
        );
        void mutateDetail();
        await mutateHistory();
      } catch (error) {
        toast(
          error instanceof Error ? error.message : "Could not send message",
          "error",
        );
      }
    },
    [
      conversationId,
      currentRun,
      mutateDetail,
      mutateCache,
      mutateHistory,
      router,
      selectedProjectId,
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

  const runtime = useExternalStoreRuntime({
    messages: uiMessages,
    convertMessage: (message: UiMessage): ThreadMessageLike => {
      const metadataRunId =
        message.runId ??
        (typeof message.metadata.run_id === "string"
          ? message.metadata.run_id
          : undefined);
      const metadataStatus =
        message.runStatus ??
        (typeof message.metadata.status === "string"
          ? (message.metadata.status as StandaloneChatRunStatus)
          : "completed");
      return {
        id: message.id,
        role: message.role,
        content: [{ type: "text", text: message.content }],
        createdAt: new Date(message.created_at * 1_000),
        ...(message.role === "assistant"
          ? {
              status:
                metadataStatus === "queued" || metadataStatus === "running"
                  ? ({ type: "running" } as const)
                  : metadataStatus === "failed"
                    ? ({
                        type: "incomplete",
                        reason: "error",
                      } as const)
                    : metadataStatus === "cancelled"
                      ? ({
                          type: "incomplete",
                          reason: "cancelled",
                        } as const)
                      : ({ type: "complete", reason: "stop" } as const),
              metadata: {
                custom: {
                  runId: metadataRunId,
                  runStatus: metadataStatus,
                  synthetic: message.synthetic ?? false,
                },
              },
            }
          : {}),
      };
    },
    isRunning:
      currentRun?.status === "queued" || currentRun?.status === "running",
    isSendDisabled:
      !selectedProjectId ||
      (readiness?.ready === false &&
        currentRun?.status !== "waiting_for_user") ||
      currentRun?.status === "queued" ||
      currentRun?.status === "running",
    onNew: submitMessage,
    onCancel: currentRun ? () => onStop(currentRun.id) : undefined,
    adapters: {
      threadList: {
        threadId: conversationId,
        threads: (historyData?.conversations ?? []).map((conversation) => ({
          status: "regular" as const,
          id: conversation.id,
          remoteId: conversation.id,
          title: conversation.title,
          custom: {
            projectId: conversation.project_id,
            runStatus: conversation.run_status,
          },
        })),
        onSwitchToNewThread: () => router.push("/chats"),
        onSwitchToThread: (threadId) => router.push(`/chats/${threadId}`),
        onRename: async (threadId, title) => {
          await renameStandaloneConversation(threadId, title);
          await mutateHistory();
        },
        onArchive: async (threadId) => {
          await archiveStandaloneConversation(threadId);
          await mutateHistory();
          if (threadId === conversationId) router.push("/chats");
        },
      },
    },
    unstable_capabilities: { copy: true },
  });

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
      <AssistantRuntimeProvider runtime={runtime}>
        <div className="h-screen min-w-[960px] overflow-hidden p-4">
          <div className="flex h-full overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg)] shadow-2xl shadow-black/20">
            <ConversationRail
              conversations={conversations}
              activeId={conversationId}
              onRename={(conversation) => void renameConversation(conversation)}
              onArchive={(conversation) =>
                void archiveConversation(conversation)
              }
            />
            <ThreadPrimitive.Root className="flex min-w-0 flex-1 flex-col">
              <header className="flex h-16 flex-none items-center justify-between border-b border-[var(--color-border)] px-6">
                <div className="flex items-center gap-3">
                  <PanelLeft className="h-4 w-4 text-[var(--color-text-dim)]" />
                  <div>
                    <div className="text-[10px] uppercase tracking-[0.15em] text-[var(--color-text-dim)]">
                      Data chat
                    </div>
                    {conversationId && detail ? (
                      <div className="max-w-xl truncate text-sm text-[var(--color-text)]">
                        {detail.conversation.title}
                      </div>
                    ) : (
                      <div className="text-sm text-[var(--color-text)]">
                        New private conversation
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-dim)]">
                    Project
                  </span>
                  <select
                    value={selectedProjectId ?? ""}
                    onChange={(event) => {
                      const projectId = event.target.value;
                      if (conversationId) {
                        router.push(
                          `/chats?project=${encodeURIComponent(projectId)}`,
                        );
                      } else {
                        setSelectedProjectId(projectId);
                        void setDefaultStandaloneChatProject(projectId);
                        router.replace(
                          `/chats?project=${encodeURIComponent(projectId)}`,
                        );
                      }
                    }}
                    aria-label={
                      conversationId
                        ? "Start a new chat with another project"
                        : "Select project"
                    }
                    className="rounded-full border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-1.5 text-xs text-[var(--color-text-muted)] focus:outline-none"
                  >
                    {bootstrap.projects.map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.display_name}
                        {project.ready
                          ? ""
                          : projectSetupSuffix(project.readiness_message)}
                      </option>
                    ))}
                  </select>
                  {conversationId && detail?.conversation.branch && (
                    <span className="text-[10px] text-[var(--color-text-dim)]">
                      {detail.conversation.branch}
                    </span>
                  )}
                  {conversationId && currentRun?.status && (
                    <span
                      className={`rounded-full border border-[var(--color-border)] px-2.5 py-1 text-[10px] ${statusTone(currentRun.status)}`}
                    >
                      {statusLabel(currentRun.status)}
                    </span>
                  )}
                </div>
              </header>
              {conversationId && unreadyMessage && (
                <div className="flex-none px-6 pt-4">
                  <ReadinessNotice
                    message={unreadyMessage}
                    showSetup={showSetupCta}
                    onSetup={() => router.push("/projects")}
                  />
                </div>
              )}
              <ThreadPrimitive.Viewport className="min-h-0 flex-1 overflow-y-auto">
                {empty ? (
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
                      <StarterQuestions questions={starters} />
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
                  <ThreadPrimitive.Messages
                    components={{ Message: ChatMessage }}
                  />
                )}
                <ThreadPrimitive.ViewportFooter className="sticky bottom-0 bg-gradient-to-t from-[var(--color-bg)] via-[var(--color-bg)] to-transparent pt-3">
                  <Composer
                    placeholder={
                      currentRun?.status === "waiting_for_user"
                        ? "Answer the clarification…"
                        : "Ask a question about this project…"
                    }
                  />
                </ThreadPrimitive.ViewportFooter>
              </ThreadPrimitive.Viewport>
            </ThreadPrimitive.Root>
          </div>
        </div>
      </AssistantRuntimeProvider>
    </ChatUiContext.Provider>
  );
}
