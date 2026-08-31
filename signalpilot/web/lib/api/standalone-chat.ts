// Chat traces and the standalone data chat.

import {
  GATEWAY_URL,
  downloadChatArtifact,
  getAuthHeaders,
  request,
} from "./client";

// The following functions support chat traces on the /chats page.
export type ChatTraceThread = {
  thread_id: string;
  session_id: string;
  source: string;
  title: string;
  status: string;
  notebook_path: string;
  created_at: number;
  updated_at: number;
  metadata: Record<string, unknown>;
};
export type ChatTraceEvent = {
  idx: number;
  type: string;
  role: string | null;
  content: string;
  tool_name: string;
  tool_input: unknown;
  is_error: boolean;
  cost_usd: number | null;
  turn: number;
  created_at: number;
};
export const listChatThreads = (source?: string) =>
  request<{ threads: ChatTraceThread[] }>(
    `/api/notebook-chat/traces/threads?limit=200${source ? `&source=${encodeURIComponent(source)}` : ""}`,
  );
export const getChatThreadEvents = (threadId: string) =>
  request<{ events: ChatTraceEvent[] }>(
    `/api/notebook-chat/traces/threads/${encodeURIComponent(threadId)}/events`,
  );

// Standalone, author-private data chat
export type StandaloneChatRunStatus =
  | "queued"
  | "running"
  | "waiting_for_user"
  | "waiting_for_query_approval"
  | "completed"
  | "failed"
  | "cancelled";

export type StandaloneChatProject = {
  id: string;
  name: string;
  display_name: string;
  connection_name: string | null;
  default_branch: string;
  ready: boolean;
  readiness_message: string;
};

export type StandaloneChatBootstrap = {
  enabled: boolean;
  projects: StandaloneChatProject[];
  selected_project_id: string | null;
  is_admin: boolean;
  starter_questions: string[];
  default_per_query_budget_usd: number;
  default_chat_budget_usd: number;
  enterprise_features: {
    query_approval?: boolean;
    structured_results?: boolean;
    organization_sharing?: boolean;
    forking?: boolean;
  };
};

export type StandaloneChatRun = {
  id: string;
  conversation_id: string;
  status: StandaloneChatRunStatus;
  retry_of_run_id: string | null;
  public_error_code: string | null;
  public_error_message: string | null;
  cancellation_requested_at: string | null;
  created_at: string;
  started_at: string | null;
  terminal_at: string | null;
  last_event_sequence: number;
  runtime_archive_available?: boolean;
};

export type StandaloneChatEvent = {
  run_id: string;
  sequence: number;
  type:
    | "status"
    | "progress"
    | "runtime_boot"
    | "steering_queued"
    | "steering_picked_up"
    | "steering_not_delivered"
    | "text_delta"
    | "thinking_delta"
    | "tool_started"
    | "tool_completed"
    | "sql"
    | "source"
    | "intermediate_result"
    | "clarification_requested"
    | "artifact_created"
    | "error"
    | "query_proposed"
    | "query_estimated"
    | "query_approval_requested"
    | "query_approved"
    | "query_declined"
    | "query_started"
    | "query_progress"
    | "query_completed"
    | "query_cancelled"
    | "plan_created"
    | "route_selected"
    | "notebook_started"
    | "cell_executed"
    | "runtime_result_created"
    | "archive_completed"
    | "kernel_stopped";
  payload: Record<string, unknown>;
  created_at: string;
};

export type StandaloneChatArtifact = {
  id: string;
  run_id: string;
  assistant_message_id: string | null;
  kind: "table" | "chart" | "report";
  filename: string;
  mime_type: string;
  snapshot: Record<string, unknown>;
  provenance: Record<string, unknown> | null;
  freshness_at: string | null;
  assumptions: string[];
  exclusions: string[];
  caveats: string[];
  parent_artifact_id: string | null;
  saved_report_id?: string | null;
  saved_report_version_id?: string | null;
  saved_report_title?: string | null;
  report_action?: "create" | "update" | "open";
  created_at: string;
  download_formats: string[];
};

export type StandaloneChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sequence: number;
  created_at: number;
  metadata: Record<string, unknown>;
};

export type StandaloneConversation = {
  id: string;
  project_id: string;
  project_name: string | null;
  branch: string;
  title: string;
  status: "active" | "archived";
  created_at: number;
  updated_at: number;
  run_status: StandaloneChatRunStatus | null;
  commit_sha: string | null;
  per_query_budget_usd: number;
  chat_budget_usd: number;
  estimated_spend_usd: number;
  actual_spend_usd: number;
  reserved_spend_usd: number;
  /** How the conversation was started; "improvement" means an automated improvement run. */
  origin?: string;
};

export type StandaloneConversationDetail = {
  conversation: StandaloneConversation;
  messages: StandaloneChatMessage[];
  artifacts: StandaloneChatArtifact[];
  current_run: StandaloneChatRun | null;
  run_events: StandaloneChatEvent[];
};

export type SharedChatArtifact = Omit<
  StandaloneChatArtifact,
  "run_id" | "provenance" | "parent_artifact_id"
>;

export type SharedConversationDetail = {
  conversation: {
    title: string;
    project_name: string | null;
    created_at: number;
    updated_at: number;
    /** How the conversation was started; "improvement" means an automated improvement run. */
    origin?: string;
  };
  messages: Array<Omit<StandaloneChatMessage, "metadata">>;
  artifacts: SharedChatArtifact[];
  shared_at: string;
};

export type StandaloneForkPreview = {
  project_id: string;
  project_name: string;
  commit_sha: string;
  per_query_budget_usd: number;
  chat_budget_usd: number;
  warehouse_cost_notice: string;
};

export const getStandaloneChatBootstrap = () =>
  request<StandaloneChatBootstrap>("/api/chat/bootstrap");
export const getStandaloneChatProjectReadiness = (projectId: string) =>
  request<{
    project_id: string;
    ready: boolean;
    code: string;
    message: string;
    setup_cta: boolean;
    branch: string | null;
    connection_name: string | null;
    starter_questions: string[];
  }>(`/api/chat/projects/${encodeURIComponent(projectId)}/readiness`);
export const setDefaultStandaloneChatProject = (projectId: string) =>
  request<void>("/api/chat/default-project", {
    method: "PUT",
    body: JSON.stringify({ project_id: projectId }),
  });
export const listStandaloneConversations = () =>
  request<{ conversations: StandaloneConversation[] }>(
    "/api/chat/conversations",
  );
export const createStandaloneConversation = (
  projectId: string,
  message: string,
  perQueryBudgetUsd = 0.25,
  chatBudgetUsd = 1,
  reportReference?: { report_id: string; version_id: string },
) =>
  request<StandaloneConversationDetail>("/api/chat/conversations", {
    method: "POST",
    body: JSON.stringify({
      project_id: projectId,
      message,
      per_query_budget_usd: perQueryBudgetUsd,
      chat_budget_usd: chatBudgetUsd,
      report_reference: reportReference,
    }),
  });
export const decideStandaloneQueryProposal = (
  proposalId: string,
  decision: "approve" | "decline",
  scope: "run_once" | "current_chat" | "user_defaults" = "run_once",
  budgets?: { perQueryBudgetUsd: number; chatBudgetUsd: number },
) =>
  request<StandaloneChatRun>(
    `/api/chat/query-proposals/${encodeURIComponent(proposalId)}/decision`,
    {
      method: "POST",
      body: JSON.stringify({
        decision,
        scope,
        per_query_budget_usd: budgets?.perQueryBudgetUsd,
        chat_budget_usd: budgets?.chatBudgetUsd,
      }),
    },
  );
export const getStandaloneConversation = (conversationId: string) =>
  request<StandaloneConversationDetail>(
    `/api/chat/conversations/${encodeURIComponent(conversationId)}`,
  );
export const renameStandaloneConversation = (
  conversationId: string,
  title: string,
) =>
  request<{ id: string; title: string }>(
    `/api/chat/conversations/${encodeURIComponent(conversationId)}`,
    { method: "PATCH", body: JSON.stringify({ title }) },
  );
export const archiveStandaloneConversation = (conversationId: string) =>
  request<void>(
    `/api/chat/conversations/${encodeURIComponent(conversationId)}`,
    {
      method: "DELETE",
    },
  );
export const shareStandaloneConversation = (conversationId: string) =>
  request<{ token: string; created_at: string }>(
    `/api/chat/conversations/${encodeURIComponent(conversationId)}/share`,
    { method: "POST" },
  );
export const revokeStandaloneConversationShare = (conversationId: string) =>
  request<void>(
    `/api/chat/conversations/${encodeURIComponent(conversationId)}/share`,
    { method: "DELETE" },
  );
export const getSharedStandaloneConversation = (token: string) =>
  request<SharedConversationDetail>(
    `/api/chat/shared/${encodeURIComponent(token)}`,
  );
export const getSharedStandaloneForkPreview = (token: string) =>
  request<StandaloneForkPreview>(
    `/api/chat/shared/${encodeURIComponent(token)}/fork-preview`,
  );
export const forkSharedStandaloneConversation = (
  token: string,
  perQueryBudgetUsd: number,
  chatBudgetUsd: number,
) =>
  request<{ id: string }>(
    `/api/chat/shared/${encodeURIComponent(token)}/fork`,
    {
      method: "POST",
      body: JSON.stringify({
        confirmed: true,
        per_query_budget_usd: perQueryBudgetUsd,
        chat_budget_usd: chatBudgetUsd,
      }),
    },
  );
export const createStandaloneRun = (
  conversationId: string,
  message: string,
  reportReference?: { report_id: string; version_id: string },
) =>
  request<StandaloneChatRun>(
    `/api/chat/conversations/${encodeURIComponent(conversationId)}/runs`,
    {
      method: "POST",
      body: JSON.stringify({
        message,
        report_reference: reportReference,
      }),
    },
  );
export const cancelStandaloneRun = (runId: string) =>
  request<StandaloneChatRun>(
    `/api/chat/runs/${encodeURIComponent(runId)}/cancel`,
    {
      method: "POST",
    },
  );
export const steerStandaloneRun = (runId: string, message: string) =>
  request<StandaloneChatMessage>(
    `/api/chat/runs/${encodeURIComponent(runId)}/steer`,
    { method: "POST", body: JSON.stringify({ message }) },
  );
export const clarifyStandaloneRun = (runId: string, message: string) =>
  request<StandaloneChatRun>(
    `/api/chat/runs/${encodeURIComponent(runId)}/clarification`,
    { method: "POST", body: JSON.stringify({ message }) },
  );
export const retryStandaloneRun = (runId: string) =>
  request<StandaloneChatRun>(
    `/api/chat/runs/${encodeURIComponent(runId)}/retry`,
    {
      method: "POST",
    },
  );

export async function streamStandaloneRunEvents(
  runId: string,
  after: number,
  signal: AbortSignal,
  onEvent: (event: StandaloneChatEvent) => void,
): Promise<void> {
  const headers = await getAuthHeaders();
  const response = await fetch(
    `${GATEWAY_URL}/api/chat/runs/${encodeURIComponent(runId)}/events?after=${after}`,
    {
      headers: { ...headers, Accept: "text/event-stream" },
      signal,
    },
  );
  if (!response.ok || !response.body) {
    throw new Error(`Could not connect to the run (${response.status})`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const dataLine = block
        .split("\n")
        .find((line) => line.startsWith("data: "));
      if (!dataLine) continue;
      onEvent(JSON.parse(dataLine.slice(6)) as StandaloneChatEvent);
    }
    if (done) break;
  }
}

export async function downloadStandaloneArtifact(
  artifactId: string,
  format: string,
  filename: string,
): Promise<void> {
  return downloadChatArtifact(
    `/api/chat/artifacts/${encodeURIComponent(artifactId)}/download?format=${encodeURIComponent(format)}`,
    format,
    filename,
  );
}

export async function getStandaloneArtifactObjectUrl(
  artifactId: string,
  format: string,
): Promise<string> {
  const headers = await getAuthHeaders();
  const response = await fetch(
    `${GATEWAY_URL}/api/chat/artifacts/${encodeURIComponent(artifactId)}/download?format=${encodeURIComponent(format)}`,
    { headers },
  );
  if (!response.ok)
    throw new Error(`Artifact preview failed (${response.status})`);
  return URL.createObjectURL(await response.blob());
}

export async function getSavedReportVersionObjectUrl(
  versionId: string,
  format: string,
): Promise<string> {
  const headers = await getAuthHeaders();
  const response = await fetch(
    `${GATEWAY_URL}/api/chat/report-versions/${encodeURIComponent(versionId)}/download?format=${encodeURIComponent(format)}`,
    { headers },
  );
  if (!response.ok)
    throw new Error(`Report preview failed (${response.status})`);
  return URL.createObjectURL(await response.blob());
}

export type ConversationNotebookDocument = {
  source: string;
  session: Record<string, unknown> | null;
};

/**
 * The conversation's notebook resource. The gateway is the single source of
 * truth: it verifies kernel liveness and selects the newest saved document.
 */
export type ConversationNotebook = {
  status: "live" | "ended" | "none";
  gateway_session_id: string | null;
  kernel_session_id: string | null;
  notebook_path: string | null;
  document: ConversationNotebookDocument | null;
};

export const getConversationNotebook = (conversationId: string) =>
  request<ConversationNotebook>(
    `/api/chat/conversations/${encodeURIComponent(conversationId)}/notebook`,
  );

export async function openStandaloneNotebookArchive(
  runId: string,
): Promise<void> {
  const pending = window.open("about:blank", "_blank");
  if (!pending) throw new Error("Notebook archive popup was blocked");
  pending.opener = null;
  const headers = await getAuthHeaders();
  const response = await fetch(
    `${GATEWAY_URL}/api/chat/runs/${encodeURIComponent(runId)}/notebook`,
    { headers },
  );
  if (!response.ok) {
    pending.close();
    throw new Error(`Notebook archive unavailable (${response.status})`);
  }
  const url = URL.createObjectURL(await response.blob());
  const document = pending.document;
  document.title = "SignalPilot analysis notebook";
  document.body.replaceChildren();
  document.body.style.margin = "0";
  document.body.style.background = "#fff";
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-scripts allow-downloads");
  frame.setAttribute("title", "Archived analysis notebook");
  frame.style.border = "0";
  frame.style.width = "100vw";
  frame.style.height = "100vh";
  frame.src = url;
  document.body.appendChild(frame);
  window.setTimeout(() => URL.revokeObjectURL(url), 5 * 60_000);
}

export async function downloadSharedStandaloneArtifact(
  token: string,
  artifactId: string,
  format: string,
  filename: string,
): Promise<void> {
  return downloadChatArtifact(
    `/api/chat/shared/${encodeURIComponent(token)}/artifacts/${encodeURIComponent(artifactId)}/download?format=${encodeURIComponent(format)}`,
    format,
    filename,
  );
}

