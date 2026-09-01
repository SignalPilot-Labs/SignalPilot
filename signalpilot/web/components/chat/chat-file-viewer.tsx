"use client";

import { AlertCircle, Download, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import {
  downloadConversationFile,
  getConversationFileObjectUrl,
  getConversationFileText,
  type ConversationFileInfo,
} from "~/lib/api";
import { formatByteSize } from "~/lib/chat-artifacts";
import { ArtifactLightbox } from "~/components/chat/artifact-lightbox";
import { ChatCode, type ChatCodeLanguage } from "~/components/chat/chat-code";
import { ChatMarkdown } from "~/components/chat/chat-markdown";
import { SandboxedHtml } from "~/components/chat/sandboxed-html";

/** Cap on displayed text so huge files cannot lock the tab. */
const MAX_TEXT_CHARS = 200_000;

function languageForFilename(filename: string): ChatCodeLanguage {
  if (/\.py$/i.test(filename)) return "python";
  if (/\.sql$/i.test(filename)) return "sql";
  if (/\.(sh|bash|zsh)$/i.test(filename)) return "bash";
  return "text";
}

type ViewerState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "text"; text: string }
  | { phase: "object-url"; url: string };

function useFileContent(
  conversationId: string,
  file: ConversationFileInfo,
): ViewerState {
  const [state, setState] = useState<ViewerState>({ phase: "loading" });
  const wantsObjectUrl = file.kind === "image";

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setState({ phase: "loading" });
    const load = wantsObjectUrl
      ? getConversationFileObjectUrl(conversationId, file.id).then((url) => {
          if (cancelled) {
            // The viewer unmounted mid-fetch. Revoke now or the blob leaks.
            URL.revokeObjectURL(url);
            return;
          }
          objectUrl = url;
          setState({ phase: "object-url", url });
        })
      : getConversationFileText(conversationId, file.id).then((text) => {
          if (!cancelled) setState({ phase: "text", text });
        });
    load.catch((error: unknown) => {
      if (!cancelled) {
        setState({
          phase: "error",
          message:
            error instanceof Error ? error.message : "Could not load the file",
        });
      }
    });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
    // content_hash changes when the file content changes.
  }, [conversationId, file.id, file.content_hash, wantsObjectUrl]);

  return state;
}

function TruncationNotice({ shownChars }: { shownChars: number }) {
  return (
    <p className="px-3.5 py-2 text-[11px] text-[var(--color-text-dim)]">
      Preview truncated to the first {shownChars.toLocaleString()} characters.
      Download the file for the full content.
    </p>
  );
}

function TextBody({
  file,
  text,
}: {
  file: ConversationFileInfo;
  text: string;
}) {
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

function ImageBody({
  file,
  url,
}: {
  file: ConversationFileInfo;
  url: string;
}) {
  const [expanded, setExpanded] = useState(false);
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
 * markdown renders, code highlights, html sandboxes, images zoom.
 */
export function ChatFileViewer({
  conversationId,
  file,
}: {
  conversationId: string;
  file: ConversationFileInfo;
}) {
  const state = useFileContent(conversationId, file);
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
          onClick={() => {
            void downloadConversationFile(
              conversationId,
              file.id,
              file.filename,
            ).catch(() => undefined);
          }}
          className="inline-flex flex-none items-center gap-1 rounded-md px-1.5 py-1 text-[10px] text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
        >
          <Download className="h-3 w-3" />
          Download
        </button>
      </div>
      {state.phase === "loading" && (
        <div className="flex items-center justify-center gap-2 px-4 py-10 text-xs text-[var(--color-text-dim)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading file…
        </div>
      )}
      {state.phase === "error" && (
        <div className="flex items-center justify-center gap-2 px-4 py-10 text-xs text-[var(--color-warning)]">
          <AlertCircle className="h-4 w-4" />
          {state.message}
        </div>
      )}
      {state.phase === "text" && <TextBody file={file} text={state.text} />}
      {state.phase === "object-url" && (
        <ImageBody file={file} url={state.url} />
      )}
    </div>
  );
}
