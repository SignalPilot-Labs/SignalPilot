"use client";

import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { ChatUiContext, type ChatUiContextValue } from "~/components/chat/chat-ui-context";
import { getConversationToolResult } from "~/lib/api/chat-results";

/**
 * "Load all rows" for the table card. Pages a governed query result in
 * 1,000-row chunks up to `totalRows` (capped at FULL_RESULT_MAX_ROWS),
 * preferring the `ChatUiContext.getToolResultRows` override (the fixture
 * harness) and falling back to the authenticated API helper.
 */

export const FULL_RESULT_PAGE_SIZE = 1000;
export const FULL_RESULT_MAX_ROWS = 10_000;

export type FullResultStatus = "idle" | "loading" | "ready" | "error";

export type FullResultColumn = { name: string; type?: string | null };

export type FullResultState = {
  rows: unknown[][];
  columns: FullResultColumn[];
  status: FullResultStatus;
  error: string | null;
  /** Starts the fetch; a no-op while loading or once ready. */
  load: () => void;
};

type Page = {
  columns: { name: string; logical_type?: string | null }[];
  rows: unknown[][];
  saved_row_count: number;
};

type Fetcher = (resultId: string, opts: { offset: number; limit: number }) => Promise<Page>;

function fetcherFor(
  ui: ChatUiContextValue | null,
  conversationId: string | null,
): Fetcher | null {
  if (ui?.getToolResultRows) return ui.getToolResultRows;
  if (!conversationId) return null;
  return (resultId, opts) => getConversationToolResult(conversationId, resultId, opts);
}

/** Pages until `target` rows are held or the server runs dry. */
export async function pageFullResult(
  fetcher: Fetcher,
  resultId: string,
  totalRows: number | null,
): Promise<{ rows: unknown[][]; columns: FullResultColumn[] }> {
  const rows: unknown[][] = [];
  let columns: FullResultColumn[] = [];
  let target = Math.min(totalRows ?? FULL_RESULT_MAX_ROWS, FULL_RESULT_MAX_ROWS);
  while (rows.length < target) {
    const limit = Math.min(FULL_RESULT_PAGE_SIZE, target - rows.length);
    const page = await fetcher(resultId, { offset: rows.length, limit });
    if (!columns.length) {
      columns = page.columns.map((column) => ({ name: column.name, type: column.logical_type }));
    }
    if (typeof page.saved_row_count === "number" && totalRows === null) {
      target = Math.min(page.saved_row_count, FULL_RESULT_MAX_ROWS);
    }
    rows.push(...page.rows);
    if (page.rows.length < limit) break;
  }
  return { rows, columns };
}

export function useFullResult(
  conversationId: string | null,
  resultId: string | null,
  totalRows: number | null = null,
): FullResultState {
  const ui = useContext(ChatUiContext);
  const [rows, setRows] = useState<unknown[][]>([]);
  const [columns, setColumns] = useState<FullResultColumn[]>([]);
  const [status, setStatus] = useState<FullResultStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  const inFlight = useRef(false);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const fetcher = fetcherFor(ui, conversationId);

  const load = useCallback(() => {
    if (!resultId || !fetcher || inFlight.current || status === "ready") return;
    inFlight.current = true;
    setStatus("loading");
    setError(null);
    pageFullResult(fetcher, resultId, totalRows)
      .then((page) => {
        if (!alive.current) return;
        setRows(page.rows);
        setColumns(page.columns);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (!alive.current) return;
        setError(err instanceof Error ? err.message : String(err));
        setStatus("error");
      })
      .finally(() => {
        inFlight.current = false;
      });
  }, [resultId, fetcher, status, totalRows]);

  return { rows, columns, status, error, load };
}
