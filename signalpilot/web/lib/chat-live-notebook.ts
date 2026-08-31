import type { ConversationNotebook, StandaloneChatEvent } from "~/lib/api";

/**
 * Client logic for the chat notebook panel.
 *
 * The gateway's conversation notebook resource is the single source of
 * truth. The client never derives notebook state from run events; events
 * only tell it WHEN to fetch the resource again.
 */

/** Event types that can change the notebook resource. */
const REFRESH_EVENT_TYPES = new Set([
  "notebook_started",
  "archive_completed",
  "kernel_stopped",
]);

/**
 * Count the events that can change the notebook resource. The panel
 * refetches when this number grows. A plain count is enough: events are
 * append-only within a conversation view.
 */
export function notebookRefreshRevision(events: StandaloneChatEvent[]): number {
  let revision = 0;
  for (const event of events) {
    if (REFRESH_EVENT_TYPES.has(event.type)) revision += 1;
  }
  return revision;
}

/** True when the notebook can attach to a running kernel. */
export function canAttachLive(
  notebook: ConversationNotebook | null,
): notebook is ConversationNotebook & {
  gateway_session_id: string;
  kernel_session_id: string;
  notebook_path: string;
} {
  return Boolean(
    notebook &&
      notebook.status === "live" &&
      notebook.gateway_session_id &&
      notebook.kernel_session_id &&
      notebook.notebook_path,
  );
}

/** True when there is anything to show in the panel. */
export function hasNotebookContent(
  notebook: ConversationNotebook | null,
): boolean {
  return Boolean(
    notebook &&
      notebook.status !== "none" &&
      (canAttachLive(notebook) || notebook.document),
  );
}

/** URL of the full-page notebook pop-out for a conversation. */
export function buildChatNotebookPopoutUrl(conversationId: string): string {
  const params = new URLSearchParams({ conversation: conversationId });
  return `/chat-notebook?${params.toString()}`;
}

/**
 * Mount key for a notebook resource. A change in any part that affects the
 * viewer boot (attach target or liveness) must remount the viewer.
 */
export function chatNotebookMountKey(notebook: ConversationNotebook): string {
  return [
    notebook.status,
    notebook.gateway_session_id ?? "",
    notebook.kernel_session_id ?? "",
    notebook.notebook_path ?? "",
  ].join(":");
}
