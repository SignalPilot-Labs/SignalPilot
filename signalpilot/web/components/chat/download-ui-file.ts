import { downloadConversationFile, type ConversationFileInfo } from "~/lib/api";
import type { ChatUiContextValue } from "~/components/chat/chat-ui-context";

/**
 * Download a file's bytes through the context override when one is set
 * (the shared page), else through the owner conversation route. Resolves
 * without doing anything when neither is available.
 */
export function downloadUiFile(
  ui: Pick<ChatUiContextValue, "conversationId" | "downloadFile">,
  file: Pick<ConversationFileInfo, "id" | "filename">,
): Promise<void> {
  if (ui.downloadFile) return ui.downloadFile(file.id, file.filename);
  if (!ui.conversationId) return Promise.resolve();
  return downloadConversationFile(ui.conversationId, file.id, file.filename);
}
