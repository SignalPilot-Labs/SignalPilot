"use client";

import { AlertTriangle, ArrowDownToLine, PanelRight } from "lucide-react";
import {
  useContext,
  useMemo,
  useState,
  type ComponentProps,
  type MouseEvent,
} from "react";
import type { ConversationFileInfo } from "~/lib/api";
import {
  FILE_REF_ORIGIN,
  fileRefBasename,
  normalizeFileRef,
  resolveFileRef,
} from "~/lib/chat-file-refs";
import { ArtifactLightbox } from "~/components/chat/artifact-lightbox";
import {
  ChatUiContext,
  type ChatUiContextValue,
} from "~/components/chat/chat-ui-context";
import { useMessageRun } from "~/components/chat/message-run-context";
import { useFileObjectUrl } from "~/components/chat/use-file-object-url";
import { useToast } from "~/components/ui/toast";
import { domProps, str } from "./attrs";
import { FileChip, downloadUiFile } from "./file-chip";

type ImageProps = ComponentProps<"img"> & { node?: unknown };

/**
 * The `img` override for chat markdown.
 *
 * External images (any scheme) render as a plain image. A relative or
 * sandbox path is a conversation file reference: it resolves against the
 * manifest in ChatUiContext and renders a figure, a pending placeholder,
 * a "not available" band, or a file chip for a non-image kind. Pending is
 * decided per message (MessageRunContext): only while the run that wrote
 * this message is still running. Without a context (the playground, the
 * file viewer) there is no manifest to resolve against: a reference the
 * sanitizer rebased onto the sentinel origin renders as the "not
 * available" band (never a broken image), and any other image is external.
 */
export function MarkdownImage(props: ImageProps) {
  const { src, alt, title, ...rest } = domProps(props);
  const ui = useContext(ChatUiContext);
  const norm = normalizeFileRef(str(src));
  if (!ui && norm !== null && str(src).startsWith(`${FILE_REF_ORIGIN}/`)) {
    return <MissingImageBand name={fileRefBasename(norm)} />;
  }
  if (!ui || norm === null) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={str(src)} alt={str(alt)} title={title} {...rest} />;
  }
  return <FileImage norm={norm} alt={str(alt)} title={title} ui={ui} />;
}

function FileImage({
  norm,
  alt,
  title,
  ui,
}: {
  norm: string;
  alt: string;
  title?: string;
  ui: ChatUiContextValue;
}) {
  const { files } = ui;
  const { runId, running } = useMessageRun();
  const file = useMemo(
    () => resolveFileRef(norm, files, { runId }),
    [norm, files, runId],
  );
  const name = fileRefBasename(norm);
  if (!file) {
    return running ? (
      <PendingFigure name={name} />
    ) : (
      <MissingImageBand name={name} />
    );
  }
  if (file.kind !== "image") return <FileChip file={file} ui={ui} />;
  return <ReadyFigure file={file} alt={alt} title={title} ui={ui} />;
}

/** Shimmer placeholder at 16:10 while the manifest catches up. Keyed by
 * the normalized path in the tree, so it resolves in place. */
function PendingFigure({ name }: { name: string }) {
  return (
    <span
      data-testid="chat-md-figure-pending"
      aria-busy="true"
      role="img"
      aria-label={`Loading ${name}`}
      className="chat-md-figure-pending"
    >
      <span className="chat-md-figure-shimmer" aria-hidden="true" />
      <span className="chat-md-figure-pending-name">{name}</span>
    </span>
  );
}

/**
 * An image reference that never resolved. A block on its own line, never
 * inline in the sentence: the reader must see at a glance that a chart is
 * missing here. A span with block display, so it is valid inside a <p>.
 */
export function MissingImageBand({ name }: { name: string }) {
  return (
    <span
      role="status"
      data-testid="chat-md-image-missing"
      className="chat-md-image-missing"
      title={name}
    >
      <AlertTriangle className="chat-md-image-missing-icon" aria-hidden />
      <span className="chat-md-image-missing-label">Image not available</span>
      <span className="chat-md-image-missing-name">{name}</span>
    </span>
  );
}

function ReadyFigure({
  file,
  alt,
  title,
  ui,
}: {
  file: ConversationFileInfo;
  alt: string;
  title?: string;
  ui: ChatUiContextValue;
}) {
  const { toast } = useToast();
  const { url, fresh, error } = useFileObjectUrl(file, ui.conversationId);
  const [open, setOpen] = useState(false);
  if (error) return <MissingImageBand name={file.filename} />;
  if (!url) return <PendingFigure name={file.filename} />;
  const caption = alt || title || "";
  const download = (event: MouseEvent) => {
    event.stopPropagation();
    void downloadUiFile(ui, file).catch(() =>
      toast("This file is no longer available.", "error"),
    );
  };
  const openPanel = (event: MouseEvent) => {
    event.stopPropagation();
    ui.openArtifact(file.id);
  };
  return (
    <figure
      className="chat-md-figure"
      data-testid="chat-md-figure"
      data-file-id={file.id}
      data-fresh={fresh ? "1" : "0"}
    >
      <span className="chat-md-figure-frame">
        <button
          type="button"
          className="chat-md-figure-button"
          aria-label={`Open ${file.filename} full size`}
          onClick={() => setOpen(true)}
        >
          {/* Object URLs cannot go through next/image. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            key={url}
            src={url}
            alt={caption || file.filename}
            title={title}
            className="chat-md-figure-img"
          />
        </button>
        <span className="chat-md-figure-actions">
          <button
            type="button"
            data-testid="chat-md-figure-open"
            aria-label={`Open ${file.filename} in panel`}
            title="Open in panel"
            onClick={openPanel}
            className="chat-md-figure-action"
          >
            <PanelRight className="chat-md-figure-action-icon" aria-hidden />
            Open in panel
          </button>
          <button
            type="button"
            data-testid="chat-md-figure-download"
            aria-label={`Download ${file.filename}`}
            title="Download"
            onClick={download}
            className="chat-md-figure-action"
          >
            <ArrowDownToLine className="chat-md-figure-action-icon" aria-hidden />
            Download
          </button>
        </span>
      </span>
      {caption && <figcaption className="chat-md-figcaption">{caption}</figcaption>}
      <ArtifactLightbox open={open} title={file.filename} onClose={() => setOpen(false)}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={url}
          alt={caption || file.filename}
          className="max-h-[86vh] max-w-[92vw] rounded-md"
        />
      </ArtifactLightbox>
    </figure>
  );
}
