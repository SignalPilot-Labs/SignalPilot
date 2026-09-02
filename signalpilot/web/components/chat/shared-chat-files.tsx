"use client";

// Read-only file surfaces for the shared conversation page: the files list
// under the transcript and the lightbox the inline figures and chips open.
// The page has no artifacts panel, so this is the whole viewer.

import { Download, Loader2 } from "lucide-react";
import type { ConversationFileInfo } from "~/lib/api";
import { formatByteSize } from "~/lib/chat-artifacts";
import { middleTruncate } from "~/lib/chat-artifact-cards";
import { kindIcon } from "~/components/chat/artifacts-panel";
import { ArtifactLightbox } from "~/components/chat/artifact-lightbox";
import { useFileObjectUrl } from "~/components/chat/use-file-object-url";

export type SharedFileActions = {
  /** Opens an image in the lightbox; downloads anything else. */
  open: (file: ConversationFileInfo) => void;
  download: (file: ConversationFileInfo) => void;
};

export function SharedFilesSection({
  files,
  actions,
}: {
  files: ConversationFileInfo[];
  actions: SharedFileActions;
}) {
  if (files.length === 0) return null;
  return (
    <section
      data-testid="shared-chat-files"
      className="mt-8 border-t border-[var(--color-border)] pt-6"
    >
      <h2 className="mb-4 text-xs uppercase tracking-[0.14em] text-[var(--color-text-dim)]">
        Files
      </h2>
      <ul className="space-y-1.5">
        {files.map((file) => (
          <li
            key={file.id}
            data-testid="shared-chat-file-row"
            data-file-id={file.id}
            className="flex items-center gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-2"
          >
            {kindIcon(file.kind, "h-3.5 w-3.5 flex-none text-[var(--color-text-dim)]")}
            <button
              type="button"
              title={file.path}
              onClick={() => actions.open(file)}
              className="min-w-0 flex-1 truncate text-left font-mono text-xs text-[var(--color-text)] hover:underline"
            >
              {middleTruncate(file.filename, 60)}
            </button>
            <span className="flex-none text-[10px] text-[var(--color-text-dim)]">
              {formatByteSize(file.byte_size)}
            </span>
            <button
              type="button"
              aria-label={`Download ${file.filename}`}
              onClick={() => actions.download(file)}
              className="inline-flex flex-none items-center gap-1 rounded-md px-1.5 py-1 text-[10px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
            >
              <Download className="h-3 w-3" />
              Download
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Fullscreen image viewer for one shared file. Must render inside the
 * page's ChatUiContext provider so the object URL comes through the
 * shared content route override.
 */
export function SharedFileLightbox({
  file,
  onClose,
}: {
  file: ConversationFileInfo | null;
  onClose: () => void;
}) {
  const { url, error } = useFileObjectUrl(file, null);
  return (
    <ArtifactLightbox open={file !== null} title={file?.filename ?? ""} onClose={onClose}>
      {error ? (
        <p className="text-sm text-[var(--color-text-muted)]">
          This file is no longer available.
        </p>
      ) : url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={url}
          alt={file?.filename ?? ""}
          className="max-h-[86vh] max-w-[92vw] rounded-md"
        />
      ) : (
        <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
      )}
    </ArtifactLightbox>
  );
}
