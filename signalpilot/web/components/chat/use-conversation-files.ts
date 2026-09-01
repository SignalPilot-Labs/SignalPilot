"use client";

import { useEffect, useRef, useState } from "react";
import {
  getConversationFiles,
  getConversationSqlTrace,
  type ConversationFileInfo,
  type SqlTraceExecution,
} from "~/lib/api";

/** Delay before a refetch so bursts of events cause one request. */
const REFETCH_DEBOUNCE_MS = 400;

/** A conversation resource plus whether its first fetch has resolved. */
export type ConversationResource<T> = {
  data: T;
  /** False only before the first response for the current conversation. */
  loaded: boolean;
};

/**
 * Fetch a conversation-level resource and keep it current.
 *
 * The gateway decides everything; run events only trigger refetches. The
 * first fetch for a conversation runs at once. Event-driven refetches
 * debounce so a burst of events causes one request. Transient fetch
 * failures keep the last known value and still count as loaded, so the
 * UI never spins forever on a flaky call.
 *
 * Test override: pass `override` to skip fetching entirely. The fixture
 * harness has no gateway.
 */
export function useConversationResource<T>(
  conversationId: string | null,
  refreshRevision: number,
  fetchResource: (conversationId: string) => Promise<T>,
  emptyValue: T,
  override?: T | null,
): ConversationResource<T> {
  const [value, setValue] = useState<T>(emptyValue);
  const [loaded, setLoaded] = useState(false);
  const latestRequestRef = useRef(0);
  const fetchedConversationRef = useRef<string | null>(null);

  useEffect(() => {
    setValue(emptyValue);
    setLoaded(false);
    // The empty value is a stable constant per hook; reset on id change only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  useEffect(() => {
    if (!conversationId || override !== undefined) return;
    const isFirstFetch = fetchedConversationRef.current !== conversationId;
    fetchedConversationRef.current = conversationId;
    const requestId = ++latestRequestRef.current;
    let cancelled = false;
    const timer = setTimeout(
      () => {
        fetchResource(conversationId)
          .then((result) => {
            if (!cancelled && latestRequestRef.current === requestId) {
              setValue(result);
              setLoaded(true);
            }
          })
          .catch(() => {
            // Keep the last known resource on transient fetch failures.
            if (!cancelled && latestRequestRef.current === requestId) {
              setLoaded(true);
            }
          });
      },
      isFirstFetch ? 0 : REFETCH_DEBOUNCE_MS,
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // fetchResource is a stable module-level function per hook.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, refreshRevision, override]);

  if (override !== undefined) {
    return { data: override ?? emptyValue, loaded: true };
  }
  return { data: value, loaded };
}

const NO_FILES: ConversationFileInfo[] = [];
const NO_EXECUTIONS: SqlTraceExecution[] = [];

const fetchFiles = (conversationId: string) =>
  getConversationFiles(conversationId).then((result) => result.files);

const fetchSqlTrace = (conversationId: string) =>
  getConversationSqlTrace(conversationId).then((result) => result.executions);

/** Fetch the conversation's file manifest and keep it current. */
export function useConversationFiles(
  conversationId: string | null,
  refreshRevision: number,
  override?: ConversationFileInfo[] | null,
): ConversationResource<ConversationFileInfo[]> {
  return useConversationResource(
    conversationId,
    refreshRevision,
    fetchFiles,
    NO_FILES,
    override,
  );
}

/** Fetch the conversation's SQL trace and keep it current. */
export function useConversationSqlTrace(
  conversationId: string | null,
  refreshRevision: number,
  override?: SqlTraceExecution[] | null,
): ConversationResource<SqlTraceExecution[]> {
  return useConversationResource(
    conversationId,
    refreshRevision,
    fetchSqlTrace,
    NO_EXECUTIONS,
    override,
  );
}
