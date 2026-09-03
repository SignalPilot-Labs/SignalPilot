// Full rows of a governed query result, scoped to the conversation that
// produced it. Backs "Load all rows" on the table tool card. Not gated by
// the structured_results plan flag: the user already saw the preview rows.

import { request } from "./client";

export type ToolResultColumn = { name: string; logical_type?: string | null };

export type ConversationToolResultPage = {
  result_id: string;
  execution_id: string | null;
  columns: ToolResultColumn[];
  rows: unknown[][];
  offset: number;
  limit: number;
  saved_row_count: number;
  query_row_count: number | null;
  completeness: string | null;
  truncation_reason: string | null;
  connection_name: string | null;
};

export const getConversationToolResult = (
  conversationId: string,
  resultId: string,
  opts: { offset?: number; limit?: number } = {},
) => {
  const params = new URLSearchParams();
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const query = params.toString();
  return request<ConversationToolResultPage>(
    `/api/chat/conversations/${encodeURIComponent(conversationId)}/results/${encodeURIComponent(resultId)}${query ? `?${query}` : ""}`,
  );
};
