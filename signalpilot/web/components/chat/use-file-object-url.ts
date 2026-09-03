"use client";

import { useContext, useEffect, useState } from "react";
import { getConversationFileObjectUrl } from "~/lib/api";
import { ChatUiContext } from "~/components/chat/chat-ui-context";

/**
 * Shared object-URL cache for conversation file bytes.
 *
 * One fetch serves every consumer of the same file version: the inline
 * figure, the card thumbnail, the panel viewer and the lightbox. Entries
 * are keyed by `${fileId}:${contentHash}`, reference counted, and revoked
 * when the last consumer unmounts. A failed fetch is not cached, so a
 * remount retries.
 */

type CacheEntry = {
  /** Resolves to the URL, or null when every consumer left before the
   * bytes arrived (the URL is revoked at once in that case). */
  promise: Promise<string | null>;
  url: string | null;
  refs: number;
};

const cache = new Map<string, CacheEntry>();

export function fileObjectUrlKey(fileId: string, contentHash: string): string {
  return `${fileId}:${contentHash}`;
}

function acquire(key: string, fetcher: () => Promise<string>): CacheEntry {
  const existing = cache.get(key);
  if (existing) {
    existing.refs += 1;
    return existing;
  }
  const entry: CacheEntry = { promise: Promise.resolve(null), url: null, refs: 1 };
  entry.promise = fetcher().then(
    (url) => {
      // An orphaned entry (released while the fetch was in flight) may
      // have been replaced under the same key by a newer one. Only revoke
      // this entry's own URL; never touch the cache slot of another entry.
      if (cache.get(key) !== entry || entry.refs === 0) {
        URL.revokeObjectURL(url);
        return null;
      }
      entry.url = url;
      return url;
    },
    (error: unknown) => {
      if (cache.get(key) === entry) cache.delete(key);
      throw error;
    },
  );
  cache.set(key, entry);
  return entry;
}

function release(key: string): void {
  const entry = cache.get(key);
  if (!entry) return;
  entry.refs -= 1;
  if (entry.refs > 0) return;
  cache.delete(key);
  if (entry.url) URL.revokeObjectURL(entry.url);
}

/** Test hook: number of live cache entries. */
export function fileObjectUrlCacheSize(): number {
  return cache.size;
}

export type FileObjectUrlState = {
  /** The object URL for the requested version, or the last resolved one
   * while a newer version loads (so the figure can crossfade). */
  url: string | null;
  /** True when `url` belongs to the requested version. */
  fresh: boolean;
  error: Error | null;
};

/**
 * Object URL for one conversation file version. Honors the ChatUiContext
 * `getFileObjectUrl` override (the fixture harness has no gateway); live
 * pages fetch through the authenticated content route.
 */
export function useFileObjectUrl(
  file: { id: string; content_hash: string } | null,
  conversationId: string | null,
): FileObjectUrlState {
  const ui = useContext(ChatUiContext);
  const override = ui?.getFileObjectUrl;
  const fileId = file?.id ?? null;
  const contentHash = file?.content_hash ?? null;
  const key = fileId && contentHash ? fileObjectUrlKey(fileId, contentHash) : null;
  const [state, setState] = useState<{
    key: string | null;
    url: string | null;
    error: Error | null;
  }>({ key: null, url: null, error: null });

  useEffect(() => {
    if (!key || !fileId) return;
    if (!override && !conversationId) return;
    let active = true;
    const entry = acquire(key, () =>
      override
        ? override(fileId)
        : getConversationFileObjectUrl(conversationId as string, fileId),
    );
    entry.promise.then(
      (url) => {
        if (active && url) setState({ key, url, error: null });
      },
      (error: unknown) => {
        if (!active) return;
        setState({
          key,
          url: null,
          error: error instanceof Error ? error : new Error(String(error)),
        });
      },
    );
    return () => {
      active = false;
      release(key);
    };
  }, [key, fileId, conversationId, override]);

  if (!key) return { url: null, fresh: false, error: null };
  return {
    url: state.error && state.key === key ? null : state.url,
    fresh: state.key === key && !state.error,
    error: state.key === key ? state.error : null,
  };
}
