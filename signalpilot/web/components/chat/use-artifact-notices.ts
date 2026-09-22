"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ConversationFileInfo, ConversationNotebook } from "~/lib/api";
import {
  ARTIFACT_NOTICE_TTL_MS,
  EMPTY_ARTIFACT_NOTICE_LEDGER,
  appendArtifactNotices,
  deriveArtifactNotices,
  type ArtifactNotice,
  type ArtifactNoticeLedger,
} from "~/lib/chat-artifact-notices";

/**
 * Owns the stack of artifact notices under the artifacts toggle.
 *
 * The panel never opens by itself. Instead, when the agent starts a
 * notebook or produces a chart, dashboard or report, a notice appears
 * with a "View" action that opens the panel on that artifact. Notices
 * are suppressed while the panel is already open (the reader can see the
 * artifact land), expire on their own, and reset per conversation.
 */
export function useArtifactNotices({
  conversationId,
  notebooks,
  files,
  filesLoading,
  currentRunId,
  panelOpen,
  openArtifact,
  openNotebook,
}: {
  conversationId: string | null | undefined;
  notebooks: ConversationNotebook[];
  files: ConversationFileInfo[];
  /** True until the first file manifest of the conversation has landed. */
  filesLoading: boolean;
  currentRunId: string | null | undefined;
  panelOpen: boolean;
  /** Opens the panel on one file (from useOpenArtifact). */
  openArtifact: (fileId: string) => void;
  /** Opens the panel on the notebook tab (from useOpenArtifact). */
  openNotebook: () => void;
}) {
  const [notices, setNotices] = useState<ArtifactNotice[]>([]);
  const ledgerRef = useRef<ArtifactNoticeLedger>(EMPTY_ARTIFACT_NOTICE_LEDGER);
  // The first manifest describes history: record it, announce nothing.
  const seededRef = useRef(false);
  const timersRef = useRef(new Map<string, number>());

  const dismiss = useCallback((id: string) => {
    const timer = timersRef.current.get(id);
    if (timer !== undefined) window.clearTimeout(timer);
    timersRef.current.delete(id);
    setNotices((current) => current.filter((notice) => notice.id !== id));
  }, []);

  const dismissAll = useCallback(() => {
    for (const timer of timersRef.current.values()) window.clearTimeout(timer);
    timersRef.current.clear();
    setNotices([]);
  }, []);

  // Per-conversation reset.
  useEffect(() => {
    ledgerRef.current = EMPTY_ARTIFACT_NOTICE_LEDGER;
    seededRef.current = false;
    dismissAll();
  }, [conversationId, dismissAll]);

  useEffect(() => {
    if (!conversationId) return;
    // Wait for the first manifest so pre-existing files are seeded silently.
    if (filesLoading && !seededRef.current) return;
    const seedFiles = !seededRef.current;
    seededRef.current = true;
    const { notices: fresh, ledger } = deriveArtifactNotices({
      notebooks,
      files,
      currentRunId,
      ledger: ledgerRef.current,
      seedFiles,
    });
    ledgerRef.current = ledger;
    // With the panel open the reader watches the artifact arrive; the
    // ledger still records it so it is not announced later.
    if (fresh.length === 0 || panelOpen) return;
    setNotices((current) => appendArtifactNotices(current, fresh));
    for (const notice of fresh) {
      const timer = window.setTimeout(
        () => dismiss(notice.id),
        ARTIFACT_NOTICE_TTL_MS,
      );
      timersRef.current.set(notice.id, timer);
    }
  }, [
    conversationId,
    notebooks,
    files,
    filesLoading,
    currentRunId,
    panelOpen,
    dismiss,
  ]);

  // Opening the panel (by any route) clears the stack.
  useEffect(() => {
    if (panelOpen) dismissAll();
  }, [panelOpen, dismissAll]);

  useEffect(() => () => dismissAll(), [dismissAll]);

  const onView = useCallback(
    (notice: ArtifactNotice) => {
      dismissAll();
      if (notice.target.kind === "notebook") openNotebook();
      else openArtifact(notice.target.fileId);
    },
    [dismissAll, openArtifact, openNotebook],
  );

  // Named to spread straight into <ArtifactNotices {...result} />.
  return { notices, onView, onDismiss: dismiss };
}
