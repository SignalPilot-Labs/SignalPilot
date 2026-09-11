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
import { useMessageRun } from "~/components/chat/message-run-context";
import { LineageLink, parseLineageHref } from "~/components/chat/lineage-modal";
import { str } from "./attrs";
import { FileChip, MissingFileChip, PendingFileChip } from "./file-chip";

/** A root-relative href that is really a sandbox path, not an app route. */
const SANDBOX_PATH_RE = /signalpilot-chat-runs\/|\/artifacts\//;

/**
 * Link order: conversation file reference, then in-app route, then an
 * external anchor.
 *
 * A resolved file renders a FileChip. A relative href that does not
 * resolve renders pending (only while this message's own run is still
 * running) or missing at chip size. Root-relative hrefs stay next/link
 * soft navigations unless they resolve to a file or look like a sandbox
 * path. The agent's /lineage/<model>?project=<id> deep links open the
 * in-chat lineage modal on a plain click (RouteLink). Anything with a
 * scheme opens in a new tab with rel=noopener.
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
    return <RouteLink url={url} title={title}>{children}</RouteLink>;
  }
  return (
    <a href={url} title={title} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

/** In-app route: a lineage deep link opens the modal, anything else soft-navigates. */
function RouteLink({
  url,
  title,
  children,
}: {
  url: string;
  title?: string;
  children: ReactNode;
}) {
  const lineage = parseLineageHref(url);
  if (lineage) {
    return <LineageLink link={lineage} title={title}>{children}</LineageLink>;
  }
  return (
    <Link href={url} title={title}>
      {children}
    </Link>
  );
}

function FileLink({ norm, ui }: { norm: string; ui: ChatUiContextValue }) {
  const { runId, running } = useMessageRun();
  const file = useMemo(
    () => resolveFileRef(norm, ui.files, { runId }),
    [norm, ui.files, runId],
  );
  if (file) return <FileChip file={file} ui={ui} />;
  const name = fileRefBasename(norm);
  return running ? (
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
  const { runId } = useMessageRun();
  const file = useMemo(
    () => resolveFileRef(norm, ui.files, { runId }),
    [norm, ui.files, runId],
  );
  if (file) return <FileChip file={file} ui={ui} />;
  return <RouteLink url={url} title={title}>{children}</RouteLink>;
}
