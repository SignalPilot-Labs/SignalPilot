import type {
  ConversationFileInfo,
  ConversationNotebook,
  SqlTraceExecution,
  StandaloneChatEvent,
} from "~/lib/api";
import { hasNotebookContent } from "~/lib/chat-live-notebook";

/**
 * Client logic for the chat artifacts panel.
 *
 * The gateway's conversation resources are the single source of truth.
 * The client never derives file or trace state from run events; events
 * only tell it WHEN to fetch each resource again.
 */

/** Event types that can change the conversation file manifest.
 *
 * "status" is included because the worker debounces files_changed: the
 * final write of a run can land inside the debounce window and emit no
 * event. Status transitions are rare, so the extra refetches are cheap
 * and the run's end always triggers one last manifest fetch. */
const FILES_REFRESH_EVENT_TYPES = new Set([
  "files_changed",
  "files_archived",
  "status",
]);

/** Event types that can change the conversation SQL trace. */
const SQL_TRACE_REFRESH_EVENT_TYPES = new Set([
  "sql",
  "query_completed",
  "query_cancelled",
]);

function countRefreshEvents(
  events: StandaloneChatEvent[],
  types: Set<string>,
): number {
  let revision = 0;
  for (const event of events) {
    if (types.has(event.type)) revision += 1;
  }
  return revision;
}

/**
 * Count the events that can change the file manifest. The panel refetches
 * when this number grows. A plain count is enough: events are append-only
 * within a conversation view.
 */
export function filesRefreshRevision(events: StandaloneChatEvent[]): number {
  return countRefreshEvents(events, FILES_REFRESH_EVENT_TYPES);
}

/** Count the events that can change the SQL trace. Same contract as above. */
export function sqlTraceRefreshRevision(events: StandaloneChatEvent[]): number {
  return countRefreshEvents(events, SQL_TRACE_REFRESH_EVENT_TYPES);
}

/** True when any artifacts tab has something to show. Accepts one notebook
 * or the conversation's full notebook list. */
export function hasArtifactsContent(
  notebook: ConversationNotebook | ConversationNotebook[] | null,
  files: ConversationFileInfo[],
  executions: SqlTraceExecution[],
): boolean {
  const notebookContent = Array.isArray(notebook)
    ? notebook.some(hasNotebookContent)
    : hasNotebookContent(notebook);
  return notebookContent || files.length > 0 || executions.length > 0;
}

/** Format a byte count for display, e.g. "1.2 KB" or "3.4 MB". */
export function formatByteSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "0 B";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = "B";
  for (const next of units) {
    if (value < 1024) break;
    value /= 1024;
    unit = next;
  }
  return `${value.toFixed(1)} ${unit}`;
}

/** Human-readable label for a file kind. */
export function fileKindLabel(kind: string): string {
  switch (kind) {
    case "markdown":
      return "Markdown";
    case "code":
      return "Code";
    case "html":
      return "HTML";
    case "image":
      return "Image";
    case "notebook":
      return "Notebook";
    case "data":
      return "Data";
    default:
      return "File";
  }
}
