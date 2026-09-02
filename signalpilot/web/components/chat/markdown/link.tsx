"use client";

import Link from "next/link";
import {
  useContext,
  useMemo,
  type ComponentProps,
  type ReactNode,
} from "react";
import { fileRefBasename, normalizeFileRef, resolveFileRef } from "~/lib/chat-file-refs";
import {
  ChatUiContext,
  type ChatUiContextValue,
} from "~/components/chat/chat-ui-context";
import { str } from "./attrs";
import { FileChip, MissingFileChip, PendingFileChip } from "./file-chip";

/** A root-relative href that is really a sandbox path, not an app route. */
const SANDBOX_PATH_RE = /signalpilot-chat-runs\/|\/artifacts\//;

/**
 * Link order: conversation file reference, then in-app route, then an
 * external anchor.
 *
 * A resolved file renders a FileChip. A relative href that does not
 * resolve renders pending or missing at chip size. Root-relative hrefs
 * (the agent's /lineage/<model> deep links) stay next/link soft
 * navigations unless they resolve to a file or look like a sandbox path.
 * Anything with a scheme opens in a new tab with rel=noopener.
 */
export function MarkdownLink({
  children,
  href,
  title,
}: ComponentProps<"a"> & { node?: unknown }) {
  const url = str(href);
  const ui = useContext(ChatUiContext);
  const rootRelative = url.startsWith("/") && !url.startsWith("//");
  const norm = ui ? normalizeFileRef(url) : null;
  if (ui && norm && (!rootRelative || SANDBOX_PATH_RE.test(url))) {
    return <FileLink norm={norm} ui={ui} />;
  }
  if (ui && norm && rootRelative) {
    return <ResolvedOrRoute norm={norm} ui={ui} url={url} title={title}>{children}</ResolvedOrRoute>;
  }
  if (rootRelative) {
    return (
      <Link href={url} title={title}>
        {children}
      </Link>
    );
  }
  return (
    <a href={url} title={title} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

function FileLink({ norm, ui }: { norm: string; ui: ChatUiContextValue }) {
  const file = useMemo(
    () => resolveFileRef(norm, ui.files, { runId: ui.runningRunId }),
    [norm, ui.files, ui.runningRunId],
  );
  if (file) return <FileChip file={file} ui={ui} />;
  const name = fileRefBasename(norm);
  return ui.runningRunId ? (
    <PendingFileChip name={name} />
  ) : (
    <MissingFileChip name={name} />
  );
}

/** Root-relative href: a chip when it names a file, else the app route. */
function ResolvedOrRoute({
  norm,
  ui,
  url,
  title,
  children,
}: {
  norm: string;
  ui: ChatUiContextValue;
  url: string;
  title?: string;
  children: ReactNode;
}) {
  const file = useMemo(
    () => resolveFileRef(norm, ui.files, { runId: ui.runningRunId }),
    [norm, ui.files, ui.runningRunId],
  );
  if (file) return <FileChip file={file} ui={ui} />;
  return (
    <Link href={url} title={title}>
      {children}
    </Link>
  );
}
