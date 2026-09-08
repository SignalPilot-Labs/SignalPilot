"use client";

import { AlertCircle, Download, Loader2 } from "lucide-react";
import { useContext, useState } from "react";
import type { ConversationFileInfo } from "~/lib/api";
import { formatByteSize, isRunStreaming } from "~/lib/chat-artifacts";
import { ArtifactLightbox } from "~/components/chat/artifact-lightbox";
import { ChatCode, type ChatCodeLanguage } from "~/components/chat/chat-code";
import { ChatCsvPreview } from "~/components/chat/chat-csv-preview";
import { ChatMarkdown } from "~/components/chat/chat-markdown";
import { ChatUiContext } from "~/components/chat/chat-ui-context";
import { DashboardFileView } from "~/components/chat/dashboard-file-view";
import { downloadUiFile } from "~/components/chat/download-ui-file";
import { useFileText } from "~/components/chat/use-file-text";
import { SandboxedHtml } from "~/components/chat/sandboxed-html";
import { useFileObjectUrl } from "~/components/chat/use-file-object-url";

/** Cap on displayed text so huge files cannot lock the tab. */
const MAX_TEXT_CHARS = 200_000;

function languageForFilename(filename: string): ChatCodeLanguage {
  if (/\.py$/i.test(filename)) return "python";
  if (/\.sql$/i.test(filename)) return "sql";
  if (/\.(sh|bash|zsh)$/i.test(filename)) return "bash";
  return "text";
}

/** CSV and TSV get the table preview; other data kinds keep the text view. */
function isDelimitedData(file: ConversationFileInfo): boolean {
  return file.kind === "data" && /\.(csv|tsv)$/i.test(file.filename);
}

function Loading() {
  return (
    <div className="flex items-center justify-center gap-2 px-4 py-10 text-xs text-[var(--color-text-dim)]">
      <Loader2 className="h-4 w-4 animate-spin" />
      Loading file…
    </div>
  );
}

function Failed({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center gap-2 px-4 py-10 text-xs text-[var(--color-warning)]">
      <AlertCircle className="h-4 w-4" />
      {message}
    </div>
  );
}

function TruncationNotice({ shownChars }: { shownChars: number }) {
  return (
    <p className="px-3.5 py-2 text-[11px] text-[var(--color-text-dim)]">
      Preview truncated to the first {shownChars.toLocaleString()} characters.
      Download the file for the full content.
    </p>
  );
}

/** A dashboard spec resolves its datasets against the manifest and shows
 * pending tiles while the producing run still streams. Its JSON is parsed
 * in full; the display cap applies only to the raw view inside. */
function DashboardBody({ file, text }: { file: ConversationFileInfo; text: string }) {
  const ui = useContext(ChatUiContext);
  const files = ui?.files ?? [];
  const running = isRunStreaming(ui?.events ?? [], file.origin_run_id);
  return <DashboardFileView file={file} text={text} files={files} running={running} />;
}

function TextBody({
  file,
  text,
  onDownload,
}: {
  file: ConversationFileInfo;
  text: string;
  onDownload: () => void;
}) {
  if (file.kind === "dashboard") return <DashboardBody file={file} text={text} />;
  const truncated = text.length > MAX_TEXT_CHARS;
  const shown = truncated ? text.slice(0, MAX_TEXT_CHARS) : text;
  if (file.kind === "markdown") {
    return (
      <div className="px-3.5 py-3">
        <ChatMarkdown markdown={shown} />
        {truncated && <TruncationNotice shownChars={MAX_TEXT_CHARS} />}
      </div>
    );
  }
  if (file.kind === "html") {
    return (
      <SandboxedHtml
        html={shown}
        title={file.filename}
        className="h-[440px] w-full border-0 bg-white"
      />
    );
  }
  if (isDelimitedData(file)) {
    return (
      <ChatCsvPreview text={text} filename={file.filename} onDownload={onDownload} />
    );
  }
  return (
    <>
      <ChatCode
        code={shown}
        language={languageForFilename(file.filename)}
        maxHeightClass="max-h-[70vh]"
      />
      {truncated && <TruncationNotice shownChars={MAX_TEXT_CHARS} />}
    </>
  );
}

function TextViewer({
  conversationId,
  file,
  onDownload,
}: {
  conversationId: string;
  file: ConversationFileInfo;
  onDownload: () => void;
}) {
  const state = useFileText(conversationId, file);
  if (state.phase === "loading") return <Loading />;
  if (state.phase === "error") return <Failed message={state.message} />;
  return <TextBody file={file} text={state.text} onDownload={onDownload} />;
}

/** Images share the object-URL cache with the inline figure and the card
 * thumbnail, so one fetch serves every surface. */
function ImageViewer({
  conversationId,
  file,
}: {
  conversationId: string;
  file: ConversationFileInfo;
}) {
  const { url, error } = useFileObjectUrl(file, conversationId);
  const [expanded, setExpanded] = useState(false);
  if (error) return <Failed message={error.message} />;
  if (!url) return <Loading />;
  return (
    <div className="p-3">
      <button
        type="button"
        aria-label={`Open ${file.filename} full size`}
        onClick={() => setExpanded(true)}
        className="block cursor-zoom-in"
      >
        {/* Object URLs cannot go through next/image optimization. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={url}
          alt={file.filename}
          className="max-h-[60vh] max-w-full rounded-md"
        />
      </button>
      <ArtifactLightbox
        open={expanded}
        title={file.filename}
        onClose={() => setExpanded(false)}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={url}
          alt={file.filename}
          className="max-h-[86vh] max-w-[92vw] rounded-md"
        />
      </ArtifactLightbox>
    </div>
  );
}

/**
 * Read-only viewer for one conversation file. Dispatches on the file kind:
 * markdown renders, code highlights, html sandboxes, csv tabulates, images
 * zoom, dashboards render through the shared DashboardRenderer.
 */
export function ChatFileViewer({
  conversationId,
  file,
}: {
  conversationId: string;
  file: ConversationFileInfo;
}) {
  // Downloads go through the context override when one is set (the shared
  // page); owner pages use the conversation route.
  const ui = useContext(ChatUiContext);
  const download = () => {
    void downloadUiFile(
      { conversationId, downloadFile: ui?.downloadFile },
      file,
    ).catch(() => undefined);
  };
  return (
    <div
      data-testid="chat-file-viewer"
      className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]"
    >
      <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border)] px-3.5 py-2">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="truncate font-mono text-xs text-[var(--color-text)]">
            {file.filename}
          </span>
          <span className="flex-none text-[10px] text-[var(--color-text-dim)]">
            {formatByteSize(file.byte_size)}
          </span>
        </div>
        <button
          type="button"
          aria-label={`Download ${file.filename}`}
          onClick={download}
          className="inline-flex flex-none items-center gap-1 rounded-md px-1.5 py-1 text-[10px] text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
        >
          <Download className="h-3 w-3" />
          Download
        </button>
      </div>
      {file.kind === "image" ? (
        <ImageViewer conversationId={conversationId} file={file} />
      ) : (
        <TextViewer
          conversationId={conversationId}
          file={file}
          onDownload={download}
        />
      )}
    </div>
  );
}
