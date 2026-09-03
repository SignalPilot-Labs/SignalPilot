// Conversation file artifacts and the SQL trace.
// The gateway is the single source of truth for both resources.

import { GATEWAY_URL, getAuthHeaders, request } from "./client";

export type ConversationFileKind =
  | "markdown"
  | "code"
  | "html"
  | "image"
  | "notebook"
  | "data"
  | "other";

/** One agent-produced file in a conversation, manifest only. */
export type ConversationFileInfo = {
  id: string;
  path: string;
  filename: string;
  kind: ConversationFileKind;
  mime_type: string | null;
  byte_size: number;
  content_hash: string;
  origin_run_id: string | null;
  origin: string;
  status: string;
  created_at: string;
  updated_at: string;
};

/** One governed query execution in the conversation's SQL trace. */
export type SqlTraceExecution = {
  execution_id: string;
  run_id: string;
  connection_name: string;
  sql: string | null;
  sql_hash: string;
  status: string;
  query_path: string;
  estimated_cost_usd: number | null;
  actual_cost_usd: number | null;
  actual_scan_bytes: number | null;
  execution_ms: number | null;
  row_count: number | null;
  completeness: string | null;
  public_error_code: string | null;
  created_at: string;
  started_at: string | null;
  terminal_at: string | null;
};

export const getConversationFiles = (conversationId: string) =>
  request<{ files: ConversationFileInfo[] }>(
    `/api/chat/conversations/${encodeURIComponent(conversationId)}/files`,
  );

export const getConversationSqlTrace = (conversationId: string) =>
  request<{ executions: SqlTraceExecution[] }>(
    `/api/chat/conversations/${encodeURIComponent(conversationId)}/sql-trace`,
  );

async function fetchConversationFileContent(
  conversationId: string,
  fileId: string,
  download = false,
): Promise<Response> {
  const headers = await getAuthHeaders();
  const suffix = download ? "?download=1" : "";
  const response = await fetch(
    `${GATEWAY_URL}/api/chat/conversations/${encodeURIComponent(conversationId)}/files/${encodeURIComponent(fileId)}/content${suffix}`,
    { headers },
  );
  if (!response.ok) {
    throw new Error(`File content unavailable (${response.status})`);
  }
  return response;
}

/** Fetch a text file's content. Use for markdown, code, html, and data. */
export async function getConversationFileText(
  conversationId: string,
  fileId: string,
): Promise<string> {
  const response = await fetchConversationFileContent(conversationId, fileId);
  return response.text();
}

/**
 * Fetch a binary file into an object URL. Use for images and iframe sources.
 * The caller must revoke the URL when done.
 */
export async function getConversationFileObjectUrl(
  conversationId: string,
  fileId: string,
): Promise<string> {
  const response = await fetchConversationFileContent(conversationId, fileId);
  return URL.createObjectURL(await response.blob());
}

/** Download a conversation file through an authenticated fetch. */
export async function downloadConversationFile(
  conversationId: string,
  fileId: string,
  filename: string,
): Promise<void> {
  const response = await fetchConversationFileContent(
    conversationId,
    fileId,
    true,
  );
  saveBlobAs(await response.blob(), filename);
}

function saveBlobAs(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Delay the revoke one tick. Some browsers abort the download when the
  // URL is revoked synchronously after the click.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

// Shared (read-only) conversations. The gateway lists files from terminal
// runs only and gates both routes on the sharing grant.

export const getSharedConversationFiles = (token: string) =>
  request<{ files: ConversationFileInfo[] }>(
    `/api/chat/shared/${encodeURIComponent(token)}/files`,
  );

async function fetchSharedConversationFileContent(
  token: string,
  fileId: string,
  download = false,
): Promise<Response> {
  const headers = await getAuthHeaders();
  const suffix = download ? "?download=1" : "";
  const response = await fetch(
    `${GATEWAY_URL}/api/chat/shared/${encodeURIComponent(token)}/files/${encodeURIComponent(fileId)}/content${suffix}`,
    { headers },
  );
  if (!response.ok) {
    throw new Error(`File content unavailable (${response.status})`);
  }
  return response;
}

/** Object URL for a shared file's bytes. The caller revokes it. */
export async function getSharedConversationFileObjectUrl(
  token: string,
  fileId: string,
): Promise<string> {
  const response = await fetchSharedConversationFileContent(token, fileId);
  return URL.createObjectURL(await response.blob());
}

/** Download a shared conversation file through an authenticated fetch. */
export async function downloadSharedConversationFile(
  token: string,
  fileId: string,
  filename: string,
): Promise<void> {
  const response = await fetchSharedConversationFileContent(token, fileId, true);
  saveBlobAs(await response.blob(), filename);
}
