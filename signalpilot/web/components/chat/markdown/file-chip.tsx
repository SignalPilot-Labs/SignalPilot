"use client";

import { AlertTriangle, ArrowDownToLine } from "lucide-react";
import { downloadConversationFile, type ConversationFileInfo } from "~/lib/api";
import { middleTruncate } from "~/lib/chat-artifact-cards";
import { formatByteSize } from "~/lib/chat-artifacts";
import { kindIcon } from "~/components/chat/artifacts-panel";
import type { ChatUiContextValue } from "~/components/chat/chat-ui-context";
import { useToast } from "~/components/ui/toast";

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

/** Primary verb by kind. Data previews, documents open, the rest download. */
export function chipActionLabel(kind: string): "Preview" | "Open" | "Download" {
  if (kind === "data") return "Preview";
  if (kind === "html" || kind === "markdown") return "Open";
  return "Download";
}

const ICON_CLASS = "chat-md-chip-icon";

/**
 * Inline file card for a linked conversation file. Sits inside a sentence
 * (inline-block). One real button: the primary action by kind, which
 * focuses the artifacts panel or downloads the bytes.
 */
export function FileChip({
  file,
  ui,
}: {
  file: ConversationFileInfo;
  ui: Pick<ChatUiContextValue, "conversationId" | "openArtifact" | "downloadFile">;
}) {
  const { toast } = useToast();
  const action = chipActionLabel(file.kind);
  const run = () => {
    if (action === "Download") {
      void downloadUiFile(ui, file).catch(() =>
        toast("This file is no longer available.", "error"),
      );
      return;
    }
    ui.openArtifact(file.id);
  };
  return (
    <button
      type="button"
      data-testid="chat-md-file-chip"
      data-kind={file.kind}
      data-file-id={file.id}
      data-action={action.toLowerCase()}
      title={file.path}
      aria-label={`${action} ${file.filename}`}
      onClick={run}
      className="chat-md-chip"
    >
      {kindIcon(file.kind, ICON_CLASS)}
      <span className="chat-md-chip-name">{middleTruncate(file.filename, 40)}</span>
      <span className="chat-md-chip-meta">{formatByteSize(file.byte_size)}</span>
      <span className="chat-md-chip-action">
        {action === "Download" && (
          <ArrowDownToLine className="chat-md-chip-action-icon" aria-hidden />
        )}
        {action}
      </span>
    </button>
  );
}

/** A referenced file the manifest has not confirmed yet. */
export function PendingFileChip({ name }: { name: string }) {
  return (
    <span
      data-testid="chat-md-file-chip-pending"
      aria-busy="true"
      className="chat-md-chip chat-md-chip-pending"
      title={name}
    >
      <span aria-hidden="true" className="chat-md-chip-shimmer" />
      <span className="chat-md-chip-name">{middleTruncate(name, 40)}</span>
      <span className="chat-md-chip-meta">Saving…</span>
    </span>
  );
}

/** The run ended and the referenced file never arrived. Stays inline at
 * chip size with the warning tone; image references use the block band in
 * image.tsx instead. */
export function MissingFileChip({ name }: { name: string }) {
  return (
    <span
      data-testid="chat-md-file-chip-missing"
      className="chat-md-chip chat-md-chip-missing"
      title={name}
    >
      <AlertTriangle className={ICON_CLASS} aria-hidden />
      <span className="chat-md-chip-meta">File not available</span>
      <span className="chat-md-chip-name">{middleTruncate(name, 40)}</span>
    </span>
  );
}
