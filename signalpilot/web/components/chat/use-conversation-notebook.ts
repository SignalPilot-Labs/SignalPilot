"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  getConversationNotebook,
  getConversationNotebooks,
  type ConversationFileInfo,
  type ConversationNotebook,
  type SqlTraceExecution,
  type StandaloneChatEvent,
} from "~/lib/api";
import {
  useConversationFiles,
  useConversationResource,
  useConversationSqlTrace,
  type ConversationResource,
} from "~/components/chat/use-conversation-files";
import {
  filesRefreshRevision,
  sqlTraceRefreshRevision,
} from "~/lib/chat-artifacts";
import { notebookRefreshRevision } from "~/lib/chat-live-notebook";

/** Delay before a refetch so bursts of events cause one request. */
const REFETCH_DEBOUNCE_MS = 400;

/**
 * Fetch the conversation's notebook resource and keep it current.
 *
 * The gateway decides everything: kernel liveness, attach ids, and the
 * newest saved document. This hook fetches once per conversation and again
 * each time `refreshRevision` grows (the caller derives that number from
 * notebook-related run events).
 *
 * Test override: pass `override` to skip fetching entirely. The fixture
 * harness has no gateway.
 */
export function useConversationNotebook(
  conversationId: string | null,
  refreshRevision: number,
  override?: ConversationNotebook | null,
): ConversationNotebook | null {
  const [notebook, setNotebook] = useState<ConversationNotebook | null>(null);
  const latestRequestRef = useRef(0);
  const fetchedConversationRef = useRef<string | null>(null);

  useEffect(() => {
    setNotebook(null);
  }, [conversationId]);

  useEffect(() => {
    if (!conversationId || override !== undefined) return;
    // The first fetch for a conversation runs at once. Event-driven
    // refetches debounce so a burst of events causes one request.
    const isFirstFetch = fetchedConversationRef.current !== conversationId;
    fetchedConversationRef.current = conversationId;
    const requestId = ++latestRequestRef.current;
    let cancelled = false;
    const timer = setTimeout(
      () => {
        getConversationNotebook(conversationId)
          .then((result) => {
            if (!cancelled && latestRequestRef.current === requestId) {
              setNotebook(result);
            }
          })
          .catch(() => {
            /* Keep the last known resource on transient fetch failures. */
          });
      },
      isFirstFetch ? 0 : REFETCH_DEBOUNCE_MS,
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [conversationId, refreshRevision, override]);

  return override !== undefined ? (override ?? null) : notebook;
}

const NO_NOTEBOOKS: ConversationNotebook[] = [];

const fetchNotebooks = (conversationId: string) =>
  getConversationNotebooks(conversationId).then((result) => result.notebooks);

/**
 * Fetch ALL of the conversation's notebooks and keep them current. Same
 * contract as the singular hook: the gateway decides everything, events
 * only trigger refetches, and `override` skips fetching for fixtures.
 * Returns the list plus whether the first fetch has resolved.
 */
export function useConversationNotebooks(
  conversationId: string | null,
  refreshRevision: number,
  override?: ConversationNotebook[] | null,
): ConversationResource<ConversationNotebook[]> {
  return useConversationResource(
    conversationId,
    refreshRevision,
    fetchNotebooks,
    NO_NOTEBOOKS,
    override,
  );
}

/** Everything the artifacts panel renders, plus a first-load flag. */
export type ConversationArtifacts = {
  notebooks: ConversationNotebook[];
  files: ConversationFileInfo[];
  executions: SqlTraceExecution[];
  /** True until every resource has answered once for this conversation. */
  loading: boolean;
};

/**
 * Fetch all three artifacts-panel resources for one conversation. Events
 * only trigger refetches; each resource has its own refresh revision.
 */
export function useConversationArtifacts(
  conversationId: string | null,
  events: StandaloneChatEvent[],
): ConversationArtifacts {
  const notebookRev = useMemo(() => notebookRefreshRevision(events), [events]);
  const filesRev = useMemo(() => filesRefreshRevision(events), [events]);
  const sqlRev = useMemo(() => sqlTraceRefreshRevision(events), [events]);
  const notebooks = useConversationNotebooks(conversationId, notebookRev);
  const files = useConversationFiles(conversationId, filesRev);
  const sqlTrace = useConversationSqlTrace(conversationId, sqlRev);
  return {
    notebooks: notebooks.data,
    files: files.data,
    executions: sqlTrace.data,
    loading: Boolean(
      conversationId &&
        !(notebooks.loaded && files.loaded && sqlTrace.loaded),
    ),
  };
}
