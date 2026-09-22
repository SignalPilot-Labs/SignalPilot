// Artifact notices: the small "the agent started a notebook / generated a
// chart / started a dashboard" cards that sit under the artifacts toggle
// instead of the panel popping open by itself.
//
// Pure derivation: given what the panel would show and what has already
// been noticed, decide which new notices to raise. The hook in
// components/chat/use-artifact-notices.ts owns the React state; this module
// owns the rules so they stay unit-testable.

import type { ConversationFileInfo, ConversationNotebook } from "~/lib/api";
import { pickDefaultNotebook } from "~/lib/chat-live-notebook";

export type ArtifactNoticeKind = "notebook" | "chart" | "dashboard" | "report";

/** Where "View" takes the reader. */
export type ArtifactNoticeTarget =
  | { kind: "notebook" }
  | { kind: "file"; fileId: string };

export type ArtifactNotice = {
  /** Stable key; a notice is raised at most once per id. */
  id: string;
  kind: ArtifactNoticeKind;
  /** Sentence shown on the card, e.g. "The agent generated a chart". */
  title: string;
  /** Second line: the file name for file notices; empty for the notebook. */
  detail: string;
  target: ArtifactNoticeTarget;
};

/** Notices are raised only for file kinds worth interrupting for. Plain
 * code, data and markdown files stay silent: the agent writes many of them
 * and the panel toggle already shows they exist. */
const FILE_NOTICE_KINDS: Partial<
  Record<ConversationFileInfo["kind"], { kind: ArtifactNoticeKind; title: string }>
> = {
  image: { kind: "chart", title: "The agent generated a chart" },
  dashboard: { kind: "dashboard", title: "The agent started a dashboard" },
  html: { kind: "report", title: "The agent generated a report" },
};

/** Cards shown at once; older ones are dropped when a newer one arrives. */
export const MAX_VISIBLE_ARTIFACT_NOTICES = 3;

/** A notice that nobody acts on goes away on its own after this long. */
export const ARTIFACT_NOTICE_TTL_MS = 20_000;

/** Ids of everything that has been noticed (or deliberately skipped). */
export type ArtifactNoticeLedger = {
  /** Run ids whose notebook going live was already announced. */
  notebookRuns: ReadonlySet<string>;
  /** File ids already announced or seeded as pre-existing. */
  files: ReadonlySet<string>;
};

export const EMPTY_ARTIFACT_NOTICE_LEDGER: ArtifactNoticeLedger = {
  notebookRuns: new Set(),
  files: new Set(),
};

export function notebookNoticeId(runId: string): string {
  return `notebook:${runId}`;
}

export function fileNoticeId(fileId: string): string {
  return `file:${fileId}`;
}

/**
 * Decide which notices the latest artifacts state raises.
 *
 * - The default notebook going live raises one notice per run.
 * - A file not yet in the ledger raises a notice when its kind qualifies.
 *   Every file is written to the ledger regardless, so a silent kind is
 *   never re-evaluated.
 * - When `seedFiles` is true the files are only recorded, never announced:
 *   the first manifest of a conversation describes history, not news.
 *
 * Returns the notices to raise (oldest first) and the ledger to keep.
 */
export function deriveArtifactNotices({
  notebooks,
  files,
  currentRunId,
  ledger,
  seedFiles,
}: {
  notebooks: ConversationNotebook[];
  files: ConversationFileInfo[];
  currentRunId: string | null | undefined;
  ledger: ArtifactNoticeLedger;
  seedFiles: boolean;
}): { notices: ArtifactNotice[]; ledger: ArtifactNoticeLedger } {
  const notices: ArtifactNotice[] = [];
  let notebookRuns = ledger.notebookRuns;
  let seenFiles = ledger.files;

  const defaultNotebook = pickDefaultNotebook(notebooks);
  if (
    defaultNotebook?.status === "live" &&
    currentRunId &&
    !notebookRuns.has(currentRunId)
  ) {
    notebookRuns = new Set(notebookRuns).add(currentRunId);
    notices.push({
      id: notebookNoticeId(currentRunId),
      kind: "notebook",
      title: "The agent started a notebook",
      detail: "",
      target: { kind: "notebook" },
    });
  }

  for (const file of files) {
    if (seenFiles.has(file.id)) continue;
    if (seenFiles === ledger.files) seenFiles = new Set(seenFiles);
    (seenFiles as Set<string>).add(file.id);
    if (seedFiles) continue;
    const rule = FILE_NOTICE_KINDS[file.kind];
    if (!rule) continue;
    notices.push({
      id: fileNoticeId(file.id),
      kind: rule.kind,
      title: rule.title,
      detail: file.filename,
      target: { kind: "file", fileId: file.id },
    });
  }

  const nextLedger =
    notebookRuns === ledger.notebookRuns && seenFiles === ledger.files
      ? ledger
      : { notebookRuns, files: seenFiles };
  return { notices, ledger: nextLedger };
}

/** Append new notices to the visible stack, newest last, bounded. */
export function appendArtifactNotices(
  visible: ArtifactNotice[],
  incoming: ArtifactNotice[],
): ArtifactNotice[] {
  if (incoming.length === 0) return visible;
  const known = new Set(visible.map((notice) => notice.id));
  const merged = [
    ...visible,
    ...incoming.filter((notice) => !known.has(notice.id)),
  ];
  return merged.slice(-MAX_VISIBLE_ARTIFACT_NOTICES);
}
