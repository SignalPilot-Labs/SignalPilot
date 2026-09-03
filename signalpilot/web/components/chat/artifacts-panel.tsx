"use client";

import dynamic from "next/dynamic";
import { useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  ExternalLink,
  FileCode,
  FileImage,
  FileText,
  File as FileIcon,
  Globe,
  Loader2,
  NotebookPen,
  Table2,
  X,
} from "lucide-react";
import {
  buildChatNotebookPopoutUrl,
  chatNotebookMountKey,
  pickDefaultNotebook,
} from "~/lib/chat-live-notebook";
import { formatByteSize } from "~/lib/chat-artifacts";
import type {
  ConversationFileInfo,
  ConversationNotebook,
  SqlTraceExecution,
  StandaloneChatEvent,
} from "~/lib/api";
import { ChatFileViewer } from "~/components/chat/chat-file-viewer";
import { ChatUiContext } from "~/components/chat/chat-ui-context";
import { SqlTracePanel } from "~/components/chat/sql-trace-panel";
import { describeQueryExecutions } from "~/lib/chat-query-descriptions";

// The notebook runtime graph is heavy. Load it only when the panel shows a
// notebook, so /chats stays light until then.
const ChatNotebookView = dynamic(
  () => import("~/components/chat/chat-notebook-view"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
      </div>
    ),
  },
);

type ArtifactsTab = "notebook" | "files" | "queries";

export function kindIcon(
  kind: string,
  className = "h-3.5 w-3.5 flex-none text-[var(--color-text-dim)]",
) {
  switch (kind) {
    case "markdown":
      return <FileText className={className} />;
    case "code":
      return <FileCode className={className} />;
    case "html":
      return <Globe className={className} />;
    case "image":
      return <FileImage className={className} />;
    case "notebook":
      return <NotebookPen className={className} />;
    case "data":
      return <Table2 className={className} />;
    default:
      return <FileIcon className={className} />;
  }
}

/** Coarse relative timestamp for the file list, e.g. "5m ago". */
function relativeTime(iso: string): string {
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86_400)}d ago`;
}

function TabButton({
  tab,
  active,
  count,
  label,
  onSelect,
}: {
  tab: ArtifactsTab;
  active: boolean;
  count?: number;
  label: string;
  onSelect: (tab: ArtifactsTab) => void;
}) {
  return (
    <button
      type="button"
      data-testid={`artifacts-tab-${tab}`}
      aria-selected={active}
      onClick={() => onSelect(tab)}
      className={`flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-xs transition-colors ${
        active
          ? "border-[var(--color-success)] font-medium text-[var(--color-text)]"
          : "border-transparent text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
      }`}
    >
      {label}
      {count !== undefined && count > 0 && (
        <span className="rounded-full bg-[var(--color-bg-card)] px-1.5 py-px text-[10px] tabular-nums text-[var(--color-text-dim)]">
          {count}
        </span>
      )}
    </button>
  );
}

function FilesTab({
  conversationId,
  files,
  selectedFileId,
  onSelectFile,
  fileViewOverride,
}: {
  conversationId: string;
  files: ConversationFileInfo[];
  /** Controlled by the panel; null means "show the list". */
  selectedFileId: string | null;
  onSelectFile: (fileId: string | null) => void;
  fileViewOverride?: ReactNode;
}) {
  const selected = files.find((file) => file.id === selectedFileId) ?? null;

  if (files.length === 0) {
    return (
      <div
        data-testid="artifacts-files-empty"
        className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center"
      >
        <FileIcon className="h-6 w-6 text-[var(--color-text-dim)]" />
        <p className="text-sm text-[var(--color-text-muted)]">No files yet.</p>
      </div>
    );
  }

  if (selected) {
    return (
      <div
        data-testid="artifacts-file-view"
        data-file-id={selected.id}
        className="flex h-full flex-col overflow-y-auto p-3"
      >
        <button
          type="button"
          data-testid="artifacts-file-back"
          onClick={() => onSelectFile(null)}
          className="mb-2 inline-flex w-fit items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
        >
          <ArrowLeft className="h-3 w-3" />
          All files
        </button>
        {fileViewOverride ?? (
          <ChatFileViewer conversationId={conversationId} file={selected} />
        )}
      </div>
    );
  }

  return (
    <ul className="h-full space-y-1.5 overflow-y-auto p-3">
      {files.map((file) => (
        <li key={file.id}>
          <button
            type="button"
            data-testid="artifacts-file-row"
            onClick={() => onSelectFile(file.id)}
            className="flex w-full items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-2 text-left text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)]"
          >
            {kindIcon(file.kind)}
            <span className="truncate font-mono text-[11px] text-[var(--color-text)]">
              {file.filename}
            </span>
            <span className="ml-auto flex flex-none items-center gap-3 text-[10px] text-[var(--color-text-dim)]">
              <span>{formatByteSize(file.byte_size)}</span>
              <span>{relativeTime(file.updated_at)}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/**
 * Right-side panel on the chat page that shows everything the agent produced
 * for the conversation: its notebooks, written files, and the governed
 * SQL trace. With more than one notebook a chip strip switches between
 * them; "analysis" is the default selection.
 *
 * The gateway's conversation resources are rendered as-is. "Live" means the
 * gateway verified the kernel sandbox is running; anything else renders the
 * saved notebook document with a "Finished" badge.
 */
const EMPTY_EVENTS: StandaloneChatEvent[] = [];

export function ArtifactsPanel({
  conversationId,
  notebooks,
  files,
  executions,
  loading = false,
  onClose,
  openFileRequest,
  liveViewOverride,
  fileViewOverride,
}: {
  conversationId: string;
  notebooks: ConversationNotebook[];
  files: ConversationFileInfo[];
  executions: SqlTraceExecution[];
  /** True while the first resource calls are still in flight. */
  loading?: boolean;
  onClose: () => void;
  /** External "open this file" request (from an inline artifact card).
   * A new nonce re-applies the request even for the same file. */
  openFileRequest?: { fileId: string; nonce: number } | null;
  /** Test-only: rendered instead of the notebook view (the fixture harness has no gateway). */
  liveViewOverride?: ReactNode;
  /** Test-only: rendered instead of the file viewer (the fixture harness has no gateway). */
  fileViewOverride?: ReactNode;
}) {
  // The agent's one-line query descriptions live in the run events; the
  // trace rows come from the gateway without them, so join here.
  const uiContext = useContext(ChatUiContext);
  const events = uiContext?.events ?? EMPTY_EVENTS;
  const queryDescriptions = useMemo(
    () => describeQueryExecutions(events, executions),
    [events, executions],
  );
  // Notebooks that can render: live, or ended with a saved document.
  const showableNotebooks = notebooks.filter(
    (entry) => entry.status === "live" || entry.document !== null,
  );
  // null means "auto": analysis when present, else the first notebook.
  const [selectedNotebookName, setSelectedNotebookName] = useState<
    string | null
  >(null);
  useEffect(() => {
    // Selection is per conversation.
    setSelectedNotebookName(null);
  }, [conversationId]);
  const activeNotebook =
    showableNotebooks.find((entry) => entry.name === selectedNotebookName) ??
    pickDefaultNotebook(showableNotebooks);
  const live = activeNotebook?.status === "live";
  const showNotebook = activeNotebook !== null;
  const firstLoad =
    loading &&
    !showNotebook &&
    files.length === 0 &&
    executions.length === 0;
  // null means "auto": follow the default tab until the user picks one.
  const [selectedTab, setSelectedTab] = useState<ArtifactsTab | null>(null);
  // null means "show the list" — lifted so an inline card can select a file.
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  useEffect(() => {
    setSelectedFileId(null);
  }, [conversationId]);
  useEffect(() => {
    if (!openFileRequest) return;
    setSelectedTab("files");
    setSelectedFileId(openFileRequest.fileId);
  }, [openFileRequest]);
  const activeTab =
    selectedTab ??
    (showNotebook ? "notebook" : files.length > 0 ? "files" : "queries");

  return (
    <aside
      data-testid="live-notebook-panel"
      className="flex w-[46%] min-w-[420px] max-w-[820px] flex-none flex-col border-l border-[var(--color-border)] bg-[var(--color-bg)]"
    >
      <div className="flex h-11 flex-none items-center justify-between border-b border-[var(--color-border)] px-3">
        <div className="flex min-w-0 items-center gap-2">
          <NotebookPen className="h-3.5 w-3.5 flex-none text-[var(--color-text-dim)]" />
          <span className="truncate text-xs font-medium text-[var(--color-text)]">
            Artifacts
          </span>
          {activeNotebook &&
            (live ? (
              <span
                data-testid="live-notebook-status-live"
                className="flex flex-none items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-emerald-600 dark:text-emerald-400"
              >
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                Live
              </span>
            ) : (
              <span
                data-testid="live-notebook-status-finished"
                className="flex-none rounded-full bg-[var(--color-bg-card)] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-[var(--color-text-dim)]"
              >
                Finished
              </span>
            ))}
        </div>
        <div className="flex flex-none items-center gap-1">
          {showNotebook && (
            <a
              href={buildChatNotebookPopoutUrl(
                conversationId,
                activeNotebook?.name,
              )}
              target="_blank"
              rel="noopener noreferrer"
              title="Open notebook in a new tab"
              aria-label="Open notebook in a new tab"
              data-testid="live-notebook-popout"
              className="rounded p-1.5 text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
          <button
            type="button"
            onClick={onClose}
            title="Close artifacts panel"
            aria-label="Close artifacts panel"
            data-testid="live-notebook-close"
            className="rounded p-1.5 text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <div
        role="tablist"
        aria-label="Artifact types"
        className="flex flex-none items-center border-b border-[var(--color-border)] px-2"
      >
        <TabButton
          tab="notebook"
          label="Notebook"
          active={activeTab === "notebook"}
          onSelect={setSelectedTab}
        />
        <TabButton
          tab="files"
          label="Files"
          count={files.length}
          active={activeTab === "files"}
          onSelect={setSelectedTab}
        />
        <TabButton
          tab="queries"
          label="Queries"
          count={executions.length}
          active={activeTab === "queries"}
          onSelect={setSelectedTab}
        />
      </div>
      <div className="relative min-h-0 flex-1" data-testid="live-notebook-body">
        {/* First-load state: nothing has answered yet, so no tab body can be
            trusted. Never shows once any content exists. */}
        {firstLoad ? (
          <div
            data-testid="artifacts-panel-loading"
            className="flex h-full flex-col items-center justify-center gap-3"
          >
            <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
            <p className="text-xs uppercase tracking-wider text-[var(--color-text-dim)]">
              Loading artifacts...
            </p>
          </div>
        ) : (
          <>
        {/* The notebook body stays MOUNTED across tab switches. Unmounting
            would drop the kiosk websocket and re-boot the viewer on every
            return to the tab. Inactive tabs hide with display:none. */}
        <div
          className={
            activeTab === "notebook" ? "flex h-full w-full flex-col" : "hidden"
          }
        >
          {showNotebook && activeNotebook ? (
            <>
              {showableNotebooks.length > 1 && (
                <div className="flex flex-none items-center gap-1 overflow-x-auto border-b border-[var(--color-border)] px-2 py-1.5">
                  {showableNotebooks.map((entry) => {
                    const isActive = entry.name === activeNotebook.name;
                    return (
                      <button
                        key={entry.name}
                        type="button"
                        data-testid="artifacts-notebook-chip"
                        aria-pressed={isActive}
                        onClick={() => setSelectedNotebookName(entry.name)}
                        className={`flex flex-none items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[11px] transition-colors ${
                          isActive
                            ? "border-[var(--color-success)]/40 bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                            : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
                        }`}
                      >
                        {entry.status === "live" && (
                          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                        )}
                        {entry.name}
                      </button>
                    );
                  })}
                </div>
              )}
              {/* Every showable notebook stays MOUNTED across selection
                  switches, same rule as tab switching: unmounting would drop
                  its kiosk websocket. Inactive ones hide with display:none.
                  The test override renders only for the active notebook (a
                  stub has no socket to preserve). */}
              <div className="relative min-h-0 flex-1">
                {showableNotebooks.map((entry) => {
                  const isActive = entry.name === activeNotebook.name;
                  return (
                    <div
                      key={entry.name}
                      className={isActive ? "h-full w-full" : "hidden"}
                      data-testid={isActive ? "live-notebook-inline" : undefined}
                    >
                      {liveViewOverride !== undefined ? (
                        isActive ? liveViewOverride : null
                      ) : (
                        <ChatNotebookView
                          key={chatNotebookMountKey(entry)}
                          notebook={entry}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <div
              data-testid="live-notebook-empty"
              className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center"
            >
              <NotebookPen className="h-6 w-6 text-[var(--color-text-dim)]" />
              <p className="text-sm text-[var(--color-text-muted)]">
                The agent hasn&apos;t started a notebook yet.
              </p>
            </div>
          )}
        </div>
        {activeTab === "files" && (
          <FilesTab
            conversationId={conversationId}
            files={files}
            selectedFileId={selectedFileId}
            onSelectFile={setSelectedFileId}
            fileViewOverride={fileViewOverride}
          />
        )}
        {activeTab === "queries" && (
          <div className="h-full overflow-y-auto p-3">
            <SqlTracePanel
              executions={executions}
              descriptions={queryDescriptions}
            />
          </div>
        )}
          </>
        )}
      </div>
    </aside>
  );
}
