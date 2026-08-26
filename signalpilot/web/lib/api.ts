const GATEWAY_URL =
  process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300";
const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";

// The following code gets Clerk tokens in cloud mode.
// auth-context sets the token getter after Clerk loads.
// Early requests wait for Clerk initialization before they use JWT authentication.
let _clerkGetToken: (() => Promise<string | null>) | null = null;
let _resolveClerkReady: (() => void) | null = null;
const _clerkReadyPromise: Promise<void> | null = IS_CLOUD_MODE
  ? new Promise<void>((resolve) => {
      _resolveClerkReady = resolve;
    })
  : null;

export function setClerkTokenGetter(getter: () => Promise<string | null>) {
  _clerkGetToken = getter;
  if (_resolveClerkReady) {
    _resolveClerkReady();
    _resolveClerkReady = null;
  }
}

// The following code gets the local API key automatically.
// sessionStorage contains the key.
// This storage location reduces exposure to persistent XSS.
// The browser removes the key when the tab closes.
if (typeof window !== "undefined" && IS_CLOUD_MODE) {
  sessionStorage.removeItem("sp_api_key");
}

let _localKeyPromise: Promise<string | null> | null = null;

function _fetchLocalKey(): Promise<string | null> {
  if (typeof window === "undefined" || IS_CLOUD_MODE)
    return Promise.resolve(null);
  return fetch("/api/local-key")
    .then((r) => (r.ok ? r.json() : null))
    .then((data: any) => {
      if (data?.key) {
        sessionStorage.setItem("sp_api_key", data.key);
        return data.key as string;
      }
      return null;
    })
    .catch(() => null);
}

function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  if (IS_CLOUD_MODE) {
    // Cloud mode uses the Clerk JWT, never a stored sp_ key.
    return null;
  }
  const stored = sessionStorage.getItem("sp_api_key");
  if (stored) return stored;
  if (!_localKeyPromise) {
    _localKeyPromise = _fetchLocalKey();
  }
  return null;
}

export function setApiKey(key: string | null) {
  if (key) {
    sessionStorage.setItem("sp_api_key", key);
  } else {
    sessionStorage.removeItem("sp_api_key");
  }
}

// The following function sends API requests.

async function _getAuthHeader(): Promise<string | null> {
    // In cloud mode, wait for Clerk initialization and then use the JWT.
  if (IS_CLOUD_MODE) {
    if (_clerkReadyPromise && !_clerkGetToken) {
      // Wait up to 10s for Clerk to load — avoids firing unauthenticated requests
      await Promise.race([
        _clerkReadyPromise,
        new Promise((r) => setTimeout(r, 10_000)),
      ]);
    }
    if (_clerkGetToken) {
      const token = await _clerkGetToken();
      if (token) return `Bearer ${token}`;
    }
    return null;
  }
  // In local mode, use the sp_ API key.
  let apiKey = getApiKey();
  if (!apiKey && _localKeyPromise) {
    apiKey = await _localKeyPromise;
  }
  if (apiKey) return `Bearer ${apiKey}`;
  return null;
}

export async function getAuthHeaders(): Promise<Record<string, string>> {
  const auth = await _getAuthHeader();
  const h: Record<string, string> = {};
  if (auth) h["Authorization"] = auth;
  return h;
}

/**
 * Return the raw gateway authentication token without the Bearer prefix.
 * Cloud mode returns the Clerk JWT.
 * Local mode returns the sp_ API key or null when authentication is disabled.
 * The notebook proxy sends this token in the HTTP Authorization header.
 * WebSocket requests use the Sec-WebSocket-Protocol two-token format.
 * The embedded client receives the token through its authToken callback.
 */
export async function getGatewayAuthToken(): Promise<string | null> {
  const header = await _getAuthHeader();
  if (!header) return null;
  return header.startsWith("Bearer ") ? header.slice(7) : header;
}

export async function request<T>(
  path: string,
  options?: RequestInit,
  _retried = false,
): Promise<T> {
  const authHeader = await _getAuthHeader();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };
  if (authHeader) {
    headers["Authorization"] = authHeader;
  }
  const res = await fetch(`${GATEWAY_URL}${path}`, {
    ...options,
    headers,
  });
  // Clear stale credentials after a 401 or 403 response and retry once.
  if ((res.status === 401 || res.status === 403) && !_retried) {
    sessionStorage.removeItem("sp_api_key");
    _localKeyPromise = null;
    // In cloud mode, the Clerk token getter provides a fresh token.
    // In local mode, fetch the local key again.
    if (!IS_CLOUD_MODE) {
      _localKeyPromise = _fetchLocalKey();
      await _localKeyPromise;
    }
    return request<T>(path, options, true);
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// The following functions support uploads from the /evals/upload page.
// The gateway creates presigned PUT URLs for each S3 part.
// The browser uploads parts directly to S3 in parallel.
// The browser retries each part and then requests upload completion.
// File data does not pass through the gateway.
// The part uploads use XHR because fetch does not report upload progress.
export type EvalUploadResult = { reference_id: string; expires_at: string };

type EvalUploadInitiate = {
  key: string;
  upload_id: string;
  reference_id: string;
  part_size: number;
  part_urls: string[];
};

const PART_CONCURRENCY = 4;
const PART_RETRIES = 3;

function putPart(
  url: string,
  blob: Blob,
  onBytes: (loaded: number) => void,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.upload.onprogress = (e) => onBytes(e.loaded);
    xhr.onload = () => {
      const etag = xhr.getResponseHeader("ETag");
      if (xhr.status >= 200 && xhr.status < 300 && etag) {
        onBytes(blob.size);
        resolve(etag);
      } else {
        reject(
          new Error(
            `Part upload failed (${xhr.status}${etag ? "" : ", no ETag"})`,
          ),
        );
      }
    };
    xhr.onerror = () => reject(new Error("Network error during part upload"));
    xhr.send(blob);
  });
}

async function putPartWithRetry(
  url: string,
  blob: Blob,
  onBytes: (loaded: number) => void,
): Promise<string> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < PART_RETRIES; attempt++) {
    try {
      return await putPart(url, blob, onBytes);
    } catch (err) {
      lastErr = err;
      onBytes(0);
      await new Promise((r) => setTimeout(r, 1000 * 2 ** attempt));
    }
  }
  throw lastErr;
}

export async function uploadEval(
  file: File,
  notes: string,
  onProgress?: (pct: number) => void,
): Promise<EvalUploadResult> {
  let init: EvalUploadInitiate;
  try {
    init = await request<EvalUploadInitiate>("/api/evals/upload/initiate", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        size_bytes: file.size,
        notes,
      }),
    });
  } catch (err) {
    // request() includes the status and body in the error.
    // Return the status and detail for the page error message.
    const m = /^(\d{3}): (.*)$/s.exec((err as Error).message ?? "");
    if (m) {
      let detail = "";
      try {
        detail = (JSON.parse(m[2]) as { detail?: string })?.detail ?? "";
      } catch {}
      throw Object.assign(new Error(detail || m[2]), { status: Number(m[1]) });
    }
    throw err;
  }

  const partCount = init.part_urls.length;
  const loaded = new Array<number>(partCount).fill(0);
  const report = () => {
    if (onProgress) {
      const total = loaded.reduce((a, b) => a + b, 0);
      onProgress(Math.min(99, Math.round((total / file.size) * 100)));
    }
  };

  const etags = new Array<string>(partCount);
  let next = 0;
  try {
    const worker = async () => {
      while (next < partCount) {
        const i = next++;
        const blob = file.slice(
          i * init.part_size,
          Math.min((i + 1) * init.part_size, file.size),
        );
        etags[i] = await putPartWithRetry(init.part_urls[i], blob, (n) => {
          loaded[i] = n;
          report();
        });
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(PART_CONCURRENCY, partCount) }, worker),
    );
  } catch (err) {
    // Abort the upload when possible.
    // The bucket lifecycle rule removes incomplete upload data.
    request("/api/evals/upload/abort", {
      method: "POST",
      body: JSON.stringify({ key: init.key, upload_id: init.upload_id }),
    }).catch(() => {});
    throw err;
  }

  const result = await request<EvalUploadResult>("/api/evals/upload/complete", {
    method: "POST",
    body: JSON.stringify({
      key: init.key,
      upload_id: init.upload_id,
      parts: etags.map((etag, i) => ({ part_number: i + 1, etag })),
      notes,
    }),
  });
  if (onProgress) onProgress(100);
  return result;
}

// The following types and functions support evaluation runs on the /evals page.
export type EvalConfig = {
  enabled?: boolean;
  runner_image?: string;
  repo_url: string;
  repo_installation_id?: string | null;
  repo_id?: number | null;
  model: string;
  max_tasks: number;
  prompt_preamble: string;
  connection: string;
  autorun_on_knowledge_add: boolean;
  notify_emails: string[];
};
export type EvalGoldCheck = { name: string; value: number; tolerance: number };
/**
 * A checks result contains a value and a tolerance.
 * A model_rebuilt result contains a text description.
 */
export type EvalCheckResult = {
  name: string;
  passed: boolean;
  value?: number;
  tolerance?: number;
  detail?: string;
};
export type EvalGradeExpectation = { name: string; value?: number; tolerance?: number };
export type EvalGrade = {
  kind: "checks" | "model_rebuilt";
  expectations?: EvalGradeExpectation[];
} & Record<string, unknown>;
export type EvalCaptureSpec = { tables: string[]; mode: string; sample_rows: number };
export type EvalCaptureResult = {
  row_count?: number;
  grain_unique?: boolean;
  stored?: string[];
} & Record<string, unknown>;
export type EvalCoverageLayer = { total?: number; covered?: number; pct?: number | null };
export type EvalCoverageModel = {
  name: string;
  layer: string;
  covered: boolean;
  declared_by: string[];
  observed_by: string[];
};
export type EvalCoverage = {
  declared: string[];
  observed: string[];
  observed_not_declared: string[];
  per_task_observed: Record<string, string[]>;
  models_total: number | null;
  models_covered?: number;
  pct: number | null;
  by_layer?: Record<string, EvalCoverageLayer>;
  marts_pct?: number | null;
  models?: EvalCoverageModel[];
};
/** The server reports a sandbox as a name or an object. */
export type EvalSandboxRef =
  | string
  | { name?: string; backend?: string; namespace?: string; started_at?: string }
  | null;
export function evalSandboxName(ref: EvalSandboxRef | undefined): string | null {
  if (!ref) return null;
  return typeof ref === "string" ? ref : ref.name ?? null;
}
export type EvalRunTask = {
  id: string;
  title: string;
  kind: string;
  task_class: "read" | "write";
  gt: string;
  checks: EvalGoldCheck[];
  grade: EvalGrade | null;
  covers: string[];
  builds: string[];
  capture_spec: EvalCaptureSpec | null;
  status: "pending" | "running" | "done" | "cancelled";
  verdict: string | null;
  check_results?: EvalCheckResult[];
  answer?: string;
  duration_s?: number;
  started_at?: string | null;
  finished_at?: string | null;
  sandbox?: EvalSandboxRef;
  branch_name?: string | null;
  capture_result?: EvalCaptureResult | null;
  observed_tables?: string[];
  error?: string | null;
  position: number;
};
export type EvalRunSummary = {
  total?: number;
  correct?: number;
  partial?: number;
  off?: number;
  unknown?: number;
  ungraded?: number;
  error?: number;
  setup_failed?: number;
  cancelled?: number;
};
export type EvalRun = {
  id: string;
  status: "preparing" | "running" | "cancelling" | "cancelled" | "completed" | "failed";
  trigger: string;
  created_at: string;
  finished_at: string | null;
  doc_ids: string[];
  doc_titles: string[];
  repo_url: string;
  model: string;
  eval_set_name: string;
  eval_set_ref: string;
  project_repo: string;
  project_ref: string;
  build_fingerprint: string;
  kb_doc_ids: string[];
  summary: EvalRunSummary;
  progress?: unknown;
  coverage: EvalCoverage | null;
  error: string | null;
  artifact_bytes: number;
  artifacts_pruned: boolean;
  traces_pruned: boolean;
};
/** The detail route returns tasks. The list route omits tasks. */
export type EvalRunDetail = EvalRun & { tasks: EvalRunTask[] };

/** Any authenticated user can read availability. Entitlement controls all other evaluation routes. */
export type EvalAvailability = {
  enabled: boolean;
  reason: "ok" | "not_enabled_for_org";
};
export const getEvalAvailability = () => request<EvalAvailability>("/api/evals/availability");

export const getEvalConfig = () => request<EvalConfig>("/api/evals/config");
export const putEvalConfig = (
  cfg: Omit<EvalConfig, "enabled" | "runner_image">,
) =>
  request<EvalConfig>("/api/evals/config", {
    method: "PUT",
    body: JSON.stringify(cfg),
  });
export const startEvalRun = (docIds: string[], taskIds?: string[]) =>
  request<EvalRun>("/api/evals/runs", {
    method: "POST",
    body: JSON.stringify({ doc_ids: docIds, task_ids: taskIds ?? null }),
  });
/** Grade the complete set against the stored knowledge base without document overlays. */
export const startBaselineEvalRun = () => startEvalRun([]);
export const cancelEvalRun = (runId: string) =>
  request<EvalRunDetail>(`/api/evals/runs/${runId}/cancel`, { method: "POST" });
export const listEvalRuns = () =>
  request<{ runs: EvalRun[] }>("/api/evals/runs");
export const getEvalRun = (runId: string) =>
  request<EvalRunDetail>(`/api/evals/runs/${runId}`);

export type EvalTask = {
  id: string;
  class: "read" | "write";
  kind: string;
  gt: string;
  title: string;
  why: string;
  prompt: string;
  doc: string;
  checks: EvalGoldCheck[];
  grade: EvalGrade | null;
  covers: string[];
  builds: string[];
  capture: EvalCaptureSpec | null;
  setup: string;
  teardown: string;
};
export type EvalSetInfo = {
  name: string;
  description: string;
  ref: string;
  project_repo: string;
  build_fingerprint: string;
  setup: Record<string, unknown>;
  tasks: EvalTask[];
};
export const listEvalTasks = () => request<EvalSetInfo>("/api/evals/tasks");

/** Return the setup or teardown log for a write task. */
export async function getEvalSetupLog(
  runId: string,
  taskId: string,
  phase: "setup" | "teardown",
): Promise<string> {
  const headers = await getAuthHeaders();
  const res = await fetch(
    `${GATEWAY_URL}/api/evals/runs/${runId}/tasks/${encodeURIComponent(taskId)}/setup/${phase}/log`,
    { headers },
  );
  if (!res.ok) throw new Error(`${res.status}`);
  return res.text();
}

// The following types and functions support live evaluation sandboxes.
export type EvalSandbox = {
  name: string;
  backend: "kubernetes" | "docker";
  phase: "pending" | "running" | "succeeded" | "failed" | "unknown";
  reason: string;
  message: string;
  ready: boolean;
  oom_killed: boolean;
  restart_count: number;
  node: string;
  created_at: string;
  started_at: string;
  age_seconds: number | null;
  run_id: string;
  task_id: string;
  task_title: string;
  task_phase: string;
};
export type EvalSandboxInventory = {
  backend: "kubernetes" | "docker";
  live: boolean;
  supports_live_logs: boolean;
  namespace: string;
  message: string;
  sandboxes: EvalSandbox[];
};
export type EvalSandboxEvent = {
  type: string;
  reason: string;
  message: string;
  count: number;
  first_seen: string;
  last_seen: string;
  age_seconds: number | null;
  source: string;
};
export type EvalActiveTask = {
  task_id: string;
  title: string;
  phase: string;
  started_at: string;
  sandbox?: EvalSandboxRef;
};
export type EvalRunProgress = {
  run_id: string;
  status: string;
  phase: string;
  done: number;
  total: number;
  /** Tasks execute concurrently. Each active entry describes one task. */
  active: EvalActiveTask[];
  started_at: string;
  elapsed_s: number | null;
  updated_at: string;
  error: string | null;
};

export const listEvalSandboxes = () => request<EvalSandboxInventory>("/api/evals/sandboxes");
export const getEvalSandboxEvents = (name: string) =>
  request<{ backend: string; supported: boolean; message: string; events: EvalSandboxEvent[] }>(
    `/api/evals/sandboxes/${encodeURIComponent(name)}/events`,
  );
export const getEvalRunProgress = (runId: string) =>
  request<EvalRunProgress>(`/api/evals/runs/${runId}/progress`);

export type EvalLogEvent =
  | { type: "open"; sandbox: string; at: number }
  | { type: "log"; text: string; at: number }
  | { type: "error"; text: string; at: number }
  | { type: "heartbeat"; at: number }
  | { type: "end"; reason: string; at: number };

/**
 * Stream live output from one evaluation sandbox through SSE over fetch.
 * Fetch permits authentication headers on the request.
 * The server ends the stream when the sandbox exits.
 * The caller decides whether to create another subscription.
 */
export function subscribeEvalSandboxLogs(
  name: string,
  tail: number,
  cb: (event: EvalLogEvent) => void,
): () => void {
  let aborted = false;
  const controller = new AbortController();

  (async () => {
    const authHeader = await _getAuthHeader();
    if (aborted) return;
    try {
      const res = await fetch(
        `${GATEWAY_URL}/api/evals/sandboxes/${encodeURIComponent(name)}/logs/stream?tail=${tail}`,
        {
          headers: {
            Accept: "text/event-stream",
            ...(authHeader ? { Authorization: authHeader } : {}),
          },
          signal: controller.signal,
        },
      );
      if (!res.ok || !res.body) {
        cb({ type: "end", reason: `http-${res.status}`, at: Date.now() / 1000 });
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (!aborted) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try { cb(JSON.parse(line.slice(6)) as EvalLogEvent); } catch {}
        }
      }
    } catch {
      if (!aborted) cb({ type: "end", reason: "disconnected", at: Date.now() / 1000 });
    }
  })();

  return () => {
    aborted = true;
    controller.abort();
  };
}

export async function getEvalTranscript(runId: string, taskId: string): Promise<string> {
  const headers = await getAuthHeaders();
  const res = await fetch(
    `${GATEWAY_URL}/api/evals/runs/${runId}/tasks/${encodeURIComponent(taskId)}/transcript`,
    { headers },
  );
  if (!res.ok) throw new Error(`${res.status}`);
  return res.text();
}

// The following types and functions support accuracy history and regressions.
export type EvalAccuracyPoint = {
  run_id: string;
  created_at: string;
  trigger: string;
  eval_set_name: string;
  eval_set_ref: string;
  build_fingerprint: string;
  tasks_total: number;
  tasks_passed: number;
  accuracy_pct: number;
  coverage_pct: number | null;
  kb_doc_ids: string[];
};
export type EvalRegression = {
  id: string;
  run_id: string;
  created_at: string;
  baseline_run_ids: string[];
  baseline_accuracy_pct: number;
  run_accuracy_pct: number;
  drop_pct: number;
  suspected_doc_ids: string[];
  sole_change: boolean;
  flipped_tasks: { task_id: string; title: string; verdict: string }[];
  notified_at: string | null;
  recipients: string[];
};
export type EvalTaskPerformance = {
  task_id: string;
  title: string;
  kind: string;
  class: "read" | "write";
  covers: string[];
  attempts: number;
  correct: number;
  partial: number;
  off: number;
  errors: number;
  pass_rate_pct: number;
  avg_duration_s: number | null;
  last_verdict: string;
  last_run_id: string;
};
export const getEvalAccuracy = () =>
  request<{
    history: EvalAccuracyPoint[];
    regressions: EvalRegression[];
    task_performance: EvalTaskPerformance[];
  }>("/api/evals/accuracy");

// The following types and functions support run artifacts and exports.
export type EvalArtifact = { path: string; bytes: number };
export const listEvalArtifacts = (runId: string) =>
  request<{ artifacts: EvalArtifact[] }>(`/api/evals/runs/${runId}/artifacts`);
export const evalArtifactUrl = (runId: string, taskId: string, filename: string) =>
  `${GATEWAY_URL}/api/evals/runs/${runId}/artifacts/${encodeURIComponent(taskId)}/${encodeURIComponent(filename)}`;
export const evalExportUrl = (runId: string) => `${GATEWAY_URL}/api/evals/runs/${runId}/export`;

/** Fetch the file with authentication and start a browser download. */
async function downloadAuthed(url: string, filename: string): Promise<void> {
  const headers = await getAuthHeaders();
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`${res.status}`);
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}
export const downloadEvalArtifact = (runId: string, taskId: string, filename: string) =>
  downloadAuthed(evalArtifactUrl(runId, taskId, filename), filename);
export const downloadEvalRunExport = (runId: string) =>
  downloadAuthed(evalExportUrl(runId), `eval-${runId}.zip`);

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
    | "text_delta"
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
) =>
  request<StandaloneConversationDetail>("/api/chat/conversations", {
    method: "POST",
    body: JSON.stringify({
      project_id: projectId,
      message,
      per_query_budget_usd: perQueryBudgetUsd,
      chat_budget_usd: chatBudgetUsd,
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
export const createStandaloneRun = (conversationId: string, message: string) =>
  request<StandaloneChatRun>(
    `/api/chat/conversations/${encodeURIComponent(conversationId)}/runs`,
    { method: "POST", body: JSON.stringify({ message }) },
  );
export const cancelStandaloneRun = (runId: string) =>
  request<StandaloneChatRun>(
    `/api/chat/runs/${encodeURIComponent(runId)}/cancel`,
    {
      method: "POST",
    },
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

async function downloadChatArtifact(
  path: string,
  format: string,
  filename: string,
): Promise<void> {
  const headers = await getAuthHeaders();
  const response = await fetch(`${GATEWAY_URL}${path}`, { headers });
  if (!response.ok) throw new Error(`Download failed (${response.status})`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${filename.replace(/\.[^.]+$/, "")}.${format}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

// Settings
export const getSettings = () =>
  request<import("./types").GatewaySettings>("/api/settings");
export const updateSettings = (s: import("./types").GatewaySettings) =>
  request<import("./types").GatewaySettings>("/api/settings", {
    method: "PUT",
    body: JSON.stringify(s),
  });

// Connections
export const getConnections = () =>
  request<import("./types").ConnectionInfo[]>("/api/connections");
export const createConnection = (c: Record<string, unknown>) =>
  request<import("./types").ConnectionInfo>("/api/connections", {
    method: "POST",
    body: JSON.stringify(c),
  });
export const updateConnection = (
  name: string,
  updates: Record<string, unknown>,
) =>
  request<import("./types").ConnectionInfo>(`/api/connections/${name}`, {
    method: "PUT",
    body: JSON.stringify(updates),
  });
export const deleteConnection = (name: string) =>
  request<void>(`/api/connections/${name}`, { method: "DELETE" });

// The following functions support the /demo-db page.
export const getDemoConnector = () =>
  request<import("./types").DemoConnectorStatus>("/api/demo/connector");
export const createDemoConnector = (demo: string) =>
  request<import("./types").DemoConnectorCreated>("/api/demo/connector", {
    method: "POST",
    body: JSON.stringify({ demo }),
  });
export const refreshConnectionSchema = (name: string) =>
  request<{
    connection_name: string;
    table_count: number;
    message: string;
    refreshed_at?: number;
    next_refresh_in?: number | null;
  }>(`/api/connections/${name}/schema/refresh`, { method: "POST" });
export const getSchemaRefreshStatus = (name: string) =>
  request<{
    connection_name: string;
    schema_refresh_interval: number | null;
    last_schema_refresh: number | null;
    next_refresh_at: number | null;
    cached: boolean;
    cached_table_count: number;
    fingerprint: string | null;
  }>(`/api/connections/${name}/schema/refresh-status`);
export const testConnection = (name: string) =>
  request<{
    status: string;
    message: string;
    phases?: {
      phase: string;
      status: string;
      message: string;
      duration_ms?: number;
    }[];
    total_duration_ms?: number;
  }>(`/api/connections/${name}/test`, { method: "POST" });
export const getConnectionSchema = (name: string) =>
  request<{
    connection_name: string;
    db_type: string;
    table_count: number;
    tables: Record<
      string,
      {
        schema: string;
        name: string;
        columns: {
          name: string;
          type: string;
          nullable: boolean;
          primary_key?: boolean;
          comment?: string;
          stats?: { distinct_count?: number; distinct_fraction?: number };
        }[];
        foreign_keys?: {
          column: string;
          references_schema?: string;
          references_table: string;
          references_column: string;
        }[];
        indexes?: {
          name: string;
          definition?: string;
          columns?: string;
          unique?: boolean;
        }[];
        row_count?: number;
        description?: string;
        engine?: string;
        sorting_key?: string;
      }
    >;
  }>(`/api/connections/${name}/schema`);

export const cloneConnection = (name: string, newName: string) =>
  request<import("./types").ConnectionInfo>(
    `/api/connections/${name}/clone?new_name=${encodeURIComponent(newName)}`,
    { method: "POST" },
  );
export const explainQuery = (
  connection_name: string,
  sql: string,
  row_limit = 1000,
) =>
  request<{
    connection_name: string;
    sql: string;
    tables: string[];
    estimated_rows: number;
    estimated_usd: number;
    is_expensive: boolean;
    warning: string | null;
    plan: string | null;
  }>("/api/query/explain", {
    method: "POST",
    body: JSON.stringify({ connection_name, sql, row_limit }),
  });
export const searchConnectionSchema = (name: string, query: string) =>
  request<{
    connection_name: string;
    query: string;
    result_count: number;
    total_tables: number;
    tables: Record<
      string,
      {
        schema: string;
        name: string;
        columns: {
          name: string;
          type: string;
          nullable: boolean;
          primary_key?: boolean;
        }[];
        foreign_keys?: {
          column: string;
          references_table: string;
          references_column: string;
        }[];
        _matched_columns?: string[];
        _relevance_score?: number;
      }
    >;
  }>(`/api/connections/${name}/schema/search?q=${encodeURIComponent(query)}`);

// Column Exploration (ReFoRCE Spider2.0 pattern)
export const exploreColumns = (
  name: string,
  table: string,
  columns?: string[],
  options?: {
    include_stats?: boolean;
    include_values?: boolean;
    value_limit?: number;
  },
) =>
  request<{
    table: string;
    table_type: string;
    row_count: number;
    columns_explored: number;
    columns: {
      name: string;
      type: string;
      nullable: boolean;
      primary_key: boolean;
      comment?: string;
      schema_stats?: { distinct_count?: number; distinct_fraction?: number };
      value_stats?: { min: unknown; max: unknown; avg: number | null };
      sample_values?: string[];
    }[];
  }>(`/api/connections/${name}/schema/explore-columns`, {
    method: "POST",
    body: JSON.stringify({
      table,
      columns: columns || [],
      include_stats: options?.include_stats ?? true,
      include_values: options?.include_values ?? true,
      value_limit: options?.value_limit ?? 10,
    }),
  });

// Column Name Correction
export const correctColumns = (
  name: string,
  table: string,
  columns: string[],
  threshold = 0.5,
) =>
  request<{
    table: string;
    corrections: Record<
      string,
      { suggestion: string | null; distance: number; confidence: number }
    >;
    total_columns: number;
  }>(`/api/connections/${name}/schema/correct-columns`, {
    method: "POST",
    body: JSON.stringify({ table, columns, threshold }),
  });

// The following functions support schema endorsements.
export const getSchemaEndorsements = (name: string) =>
  request<{
    endorsed: string[];
    hidden: string[];
    mode: "all" | "endorsed_only";
  }>(`/api/connections/${name}/schema/endorsements`);
export const setSchemaEndorsements = (
  name: string,
  endorsements: {
    endorsed: string[];
    hidden: string[];
    mode: "all" | "endorsed_only";
  },
) =>
  request<{
    endorsed: string[];
    hidden: string[];
    mode: "all" | "endorsed_only";
  }>(`/api/connections/${name}/schema/endorsements`, {
    method: "PUT",
    body: JSON.stringify(endorsements),
  });

// The following functions support connection export and import.
export const exportConnections = (includeCredentials = false) =>
  request<{
    version: string;
    exported_at: number;
    connection_count: number;
    includes_credentials: boolean;
    connections: Record<string, unknown>[];
  }>(`/api/connections/export?include_credentials=${includeCredentials}`);

export const importConnections = (manifest: Record<string, unknown>) =>
  request<{
    imported: number;
    skipped: string[];
    errors: { name: string; error: string }[];
  }>("/api/connections/import", {
    method: "POST",
    body: JSON.stringify(manifest),
  });

// Projects (legacy dbt projects)
export const getProjects = () =>
  request<import("./types").ProjectInfo[]>("/api/projects");
export const getProject = (name: string) =>
  request<import("./types").ProjectInfo>(`/api/projects/${name}`);
export const createProject = (p: Record<string, unknown>) =>
  request<import("./types").ProjectInfo>("/api/projects", {
    method: "POST",
    body: JSON.stringify(p),
  });
export const deleteProject = (name: string) =>
  request<void>(`/api/projects/${name}`, { method: "DELETE" });
export const scanProject = (name: string) =>
  request<{ message: string; model_count: number }>(
    `/api/projects/${name}/scan`,
    { method: "POST" },
  );
export const discoverDbtCloudProjects = (
  token: string,
  account_id: string,
  host: string,
) =>
  request<{ id: number; name: string; git_url: string | null }[]>(
    "/api/dbt-cloud/projects",
    {
      method: "POST",
      body: JSON.stringify({ token, account_id, host }),
    },
  );

// The following functions support workspace projects in S3.
export const getWorkspaceProjects = (status?: string) =>
  request<{
    projects: import("./types").WorkspaceProjectInfo[];
    total: number;
  }>(`/api/workspace-projects${status ? `?status=${status}` : ""}`);
export const getWorkspaceProject = (id: string) =>
  request<import("./types").WorkspaceProjectInfo>(
    `/api/workspace-projects/${id}`,
  );
export const createWorkspaceProject = (p: {
  name: string;
  display_name: string;
  description?: string;
  source?: "managed" | "github" | "dbt-cloud";
  connection_name?: string;
  git_remote?: string;
  tags?: string[];
}) =>
  request<import("./types").WorkspaceProjectInfo>("/api/workspace-projects", {
    method: "POST",
    body: JSON.stringify(p),
  });
export const updateWorkspaceProject = (
  id: string,
  p: Record<string, unknown>,
) =>
  request<import("./types").WorkspaceProjectInfo>(
    `/api/workspace-projects/${id}`,
    { method: "PUT", body: JSON.stringify(p) },
  );
export const deleteWorkspaceProject = (id: string) =>
  request<void>(`/api/workspace-projects/${id}`, { method: "DELETE" });

// The following functions support workspace project branches.
export const getWorkspaceBranches = (projectId: string) =>
  request<{ branches: import("./types").WorkspaceBranchInfo[] }>(
    `/api/workspace-projects/${projectId}/branches`,
  );
export const createWorkspaceBranch = (
  projectId: string,
  name: string,
  fromBranch = "main",
) =>
  request<import("./types").WorkspaceBranchInfo>(
    `/api/workspace-projects/${projectId}/branches`,
    {
      method: "POST",
      body: JSON.stringify({ name, from_branch: fromBranch }),
    },
  );
export const deleteWorkspaceBranch = (projectId: string, branch: string) =>
  request<void>(`/api/workspace-projects/${projectId}/branches/${branch}`, {
    method: "DELETE",
  });

// Workspace Project Files (branch-scoped)
export const getWorkspaceFiles = (
  projectId: string,
  branch = "main",
  prefix?: string,
) =>
  request<{
    project_id: string;
    branch: string;
    prefix: string;
    files: import("./types").WorkspaceFileInfo[];
  }>(
    `/api/workspace-projects/${projectId}/branches/${branch}/files${prefix ? `?prefix=${prefix}` : ""}`,
  );
export const getWorkspaceFile = (
  projectId: string,
  branch: string,
  path: string,
) =>
  request<string>(
    `/api/workspace-projects/${projectId}/branches/${branch}/files/${path}`,
    {},
    true,
  );
export const uploadWorkspaceFile = (
  projectId: string,
  branch: string,
  path: string,
  content: string,
) =>
  request<{ key: string; size: number }>(
    `/api/workspace-projects/${projectId}/branches/${branch}/files/${path}`,
    {
      method: "PUT",
      body: content,
      headers: { "Content-Type": "text/plain" },
    },
  );
export const deleteWorkspaceFile = (
  projectId: string,
  branch: string,
  path: string,
) =>
  request<void>(
    `/api/workspace-projects/${projectId}/branches/${branch}/files/${path}`,
    { method: "DELETE" },
  );

// The following functions support the user session.
export const getUserSession = (projectId: string) =>
  request<{
    user_id: string;
    project_id: string;
    active_branch: string;
    updated_at: number;
  }>(`/api/workspace-projects/${projectId}/user-session`);
export const switchBranch = (projectId: string, branch: string) =>
  request<{
    user_id: string;
    project_id: string;
    active_branch: string;
    updated_at: number;
  }>(`/api/workspace-projects/${projectId}/user-session`, {
    method: "PUT",
    body: JSON.stringify({ branch }),
  });

// The following functions support organization API keys.
export const getApiKeys = () =>
  request<
    {
      id: string;
      name: string;
      prefix: string;
      scopes: string[];
      created_at: string;
      last_used_at: string | null;
    }[]
  >("/api/keys");
export const createApiKey = (name: string, scopes: string[]) =>
  request<{
    id: string;
    name: string;
    prefix: string;
    scopes: string[];
    created_at: string;
    last_used_at: string | null;
    raw_key: string;
  }>("/api/keys", {
    method: "POST",
    body: JSON.stringify({ name, scopes }),
  });
export const deleteApiKey = (keyId: string) =>
  request<void>(`/api/keys/${keyId}`, { method: "DELETE" });

// Sandboxes
export const getSandboxes = () =>
  request<import("./types").SandboxInfo[]>("/api/sandboxes");
export const createSandbox = (s: Record<string, unknown>) =>
  request<import("./types").SandboxInfo>("/api/sandboxes", {
    method: "POST",
    body: JSON.stringify(s),
  });
export const getSandbox = (id: string) =>
  request<import("./types").SandboxInfo>(`/api/sandboxes/${id}`);
export const deleteSandbox = (id: string) =>
  request<void>(`/api/sandboxes/${id}`, { method: "DELETE" });
export const executeSandbox = (id: string, code: string, timeout = 30) =>
  request<import("./types").ExecuteResult>(`/api/sandboxes/${id}/execute`, {
    method: "POST",
    body: JSON.stringify({ code, timeout }),
  });

// The following functions support audit records.
export const getAudit = (params?: Record<string, string | number>) => {
  const qs = params
    ? "?" +
      new URLSearchParams(
        Object.entries(params).map(([k, v]) => [k, String(v)]),
      ).toString()
    : "";
  return request<{ entries: import("./types").AuditEntry[]; total: number }>(
    `/api/audit${qs}`,
  );
};

// Audit export
export function getAuditExportUrl(
  format: "json" | "csv" = "json",
  eventType?: string,
  connectionName?: string,
): string {
  const params = new URLSearchParams({ format });
  if (eventType) params.set("event_type", eventType);
  if (connectionName) params.set("connection_name", connectionName);
  return `${GATEWAY_URL}/api/audit/export?${params}`;
}

// Query
export const executeQuery = (
  connection_name: string,
  sql: string,
  row_limit = 1000,
) =>
  request<{
    rows: Record<string, unknown>[];
    row_count: number;
    tables: string[];
    execution_ms: number;
    sql_executed: string;
  }>("/api/query", {
    method: "POST",
    body: JSON.stringify({ connection_name, sql, row_limit }),
  });

// The following functions support budgets.
export const getBudgets = () =>
  request<{ sessions: Record<string, unknown>[]; total_spent_usd: number }>(
    "/api/budget",
  );
export const createBudget = (session_id: string, budget_usd: number) =>
  request<Record<string, unknown>>("/api/budget", {
    method: "POST",
    body: JSON.stringify({ session_id, budget_usd }),
  });
export const getBudget = (session_id: string) =>
  request<Record<string, unknown>>(`/api/budget/${session_id}`);

// The following functions support notebook sessions (Runtime v2: compute is a
// sandbox behind the gateway proxy; the browser only ever sees the proxy path).
// Credentials and upstream URLs are absent from frontend JavaScript.
export type NotebookSession = {
  id: string;
  status: string; // creating | running | snapshotted | stopped | error
  project_id: string | null;
  branch: string | null;
  backend: string;
  notebook_url: string | null;
  last_ping: number | null;
  created_at: number;
};

export const createNotebookSession = (
  body: { project_id?: string | null; branch?: string } = {},
) =>
  request<NotebookSession>("/api/notebook-sessions", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getNotebookSession = () =>
  request<NotebookSession | null>("/api/notebook-sessions");

export const deleteNotebookSession = () =>
  request<void>("/api/notebook-sessions", { method: "DELETE" });

export const pingNotebookSession = (sessionId: string) =>
  request<void>(`/api/notebook-sessions/${encodeURIComponent(sessionId)}/ping`, {
    method: "POST",
  });

export type AnalysisTrail = {
  id: string;
  org_id: string;
  source: string;
  request_id: string;
  thread_id: string;
  runtime_session_id: string | null;
  project_id: string;
  branch: string;
  default_branch: string;
  notebook_path: string;
  status: string;
  latest_commit_sha: string | null;
  source_url: string | null;
  source_thread_id: string | null;
  source_request_id: string | null;
  analysis_user_id: string | null;
  metadata: Record<string, unknown>;
  created_at: number;
  updated_at: number;
};

export const resolveAnalysisTrail = (params: {
  session_id?: string;
  file?: string;
}) => {
  const qs = new URLSearchParams();
  if (params.session_id) qs.set("session_id", params.session_id);
  if (params.file) qs.set("file", params.file);
  return request<AnalysisTrail>(
    `/api/analysis-trails/resolve?${qs.toString()}`,
  );
};

// The following functions support the GitHub App.
export const getGitHubInstallUrl = () =>
  request<{ install_url: string }>("/api/github/install-url");

export const getGitHubInstallations = () =>
  request<GitHubInstallation[]>("/api/github/installations");

export const deleteGitHubInstallation = (id: string) =>
  request<void>(`/api/github/installations/${id}`, { method: "DELETE" });

export const getGitHubRepos = (installationId: string) =>
  request<GitHubRepo[]>(`/api/github/installations/${installationId}/repos`);

export const linkGitHubRepo = (body: {
  project_id: string;
  installation_id: string;
  repo_full_name: string;
  repo_id: number;
  default_branch: string;
}) =>
  request<GitHubRepoLink>("/api/github/repo-links", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getGitHubImportStatus = (repoFullName: string) =>
  request<{ stage: string; done?: number; total?: number; error?: string }>(
    `/api/github/import/status?repo_full_name=${encodeURIComponent(repoFullName)}`,
  );

export const importGitHubRepo = (body: {
  installation_id: string;
  repo_full_name: string;
  repo_id: number;
  default_branch: string;
}) =>
  request<GitHubRepoImportResult>("/api/github/import", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const unlinkGitHubRepo = (linkId: string) =>
  request<void>(`/api/github/repo-links/${linkId}`, { method: "DELETE" });

export const getGitHubRepoLinks = (projectId?: string) =>
  request<GitHubRepoLink[]>(
    `/api/github/repo-links${projectId ? `?project_id=${projectId}` : ""}`,
  );

export const getGitCredentials = (projectId: string) =>
  request<GitCredentials>(`/api/github/credentials/${projectId}`);

export const getDbtProjectDir = (projectId: string, branch?: string) =>
  request<{ dbt_project_dir: string | null; detected: string[]; source: string }>(
    `/api/workspace-projects/${projectId}/dbt-project-dir${branch ? `?branch=${encodeURIComponent(branch)}` : ""}`,
  );

// The following functions support the centrally stored dbt map.
export const getDbtMap = (projectId: string, branch?: string, includeGraph = true) => {
  const qs = new URLSearchParams();
  if (branch) qs.set("branch", branch);
  if (!includeGraph) qs.set("include_graph", "false");
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return request<DbtMapResponse>(
    `/api/workspace-projects/${projectId}/dbt-map${suffix}`,
  );
};

export const compileDbtMap = (projectId: string, branch?: string) =>
  request<{ scheduled: boolean; map: DbtMapInfo | null }>(
    `/api/workspace-projects/${projectId}/dbt-map/compile${branch ? `?branch=${encodeURIComponent(branch)}` : ""}`,
    { method: "POST" },
  );

// The following function returns gateway health.
export const getHealth = () => request<Record<string, unknown>>("/health");

// The following functions support plan limits and usage.
export interface PlanUsage {
  tier: string;
  limits: {
    connections: number | "unlimited";
    users: number | "unlimited";
    api_keys: number | "unlimited";
    queries_per_day: number | "unlimited";
    audit_retention_days: number | "unlimited";
  };
  usage: {
    connections: number;
    api_keys: number;
    queries_today: number;
  };
  features: {
    pii_redaction: boolean;
    byok: boolean;
    sso: boolean;
    budget_controls: boolean;
    audit_export: boolean;
  };
}
export const getPlan = () => request<PlanUsage>("/api/plan");

// The following functions support connection health.
export const getConnectionsHealth = () =>
  request<{ connections: import("./types").ConnectionHealthStats[] }>(
    "/api/connections/health",
  );
export const getConnectionHealth = (name: string) =>
  request<import("./types").ConnectionHealthStats>(
    `/api/connections/${name}/health`,
  );
export const getConnectionHealthHistory = (
  name: string,
  window: number = 3600,
  bucket: number = 60,
) =>
  request<{
    connection_name: string;
    window_seconds: number;
    bucket_seconds: number;
    buckets: {
      timestamp: number;
      avg_latency_ms: number | null;
      max_latency_ms: number | null;
      successes: number;
      failures: number;
      total: number;
    }[];
  }>(
    `/api/connections/${name}/health/history?window=${window}&bucket=${bucket}`,
  );

// The following functions support the query and schema caches.
export const getCacheStats = () =>
  request<{
    entries: number;
    max_entries: number;
    ttl_seconds: number;
    hits: number;
    misses: number;
    hit_rate: number;
  }>("/api/cache/stats");
export const invalidateCache = (connection_name?: string) =>
  request<{ invalidated: number; connection_name: string | null }>(
    `/api/cache/invalidate${connection_name ? `?connection_name=${encodeURIComponent(connection_name)}` : ""}`,
    { method: "POST" },
  );

// The following function detects PII.
export const detectPII = (name: string) =>
  request<{
    connection_name: string;
    tables_scanned: number;
    tables_with_pii: number;
    detections: Record<string, Record<string, string>>;
  }>(`/api/connections/${name}/detect-pii`, { method: "POST" });

// The following functions configure PII redaction.
export const getPIIConfig = (name: string) =>
  request<{ enabled: boolean; rules: Record<string, string> }>(
    `/api/connections/${name}/pii`,
  );
export const setPIIConfig = (
  name: string,
  config: { enabled: boolean; rules: Record<string, string> },
) =>
  request<{ enabled: boolean; rules: Record<string, string> }>(
    `/api/connections/${name}/pii`,
    { method: "PUT", body: JSON.stringify(config) },
  );
export const detectAndSavePII = (name: string) =>
  request<{
    connection_name: string;
    columns_flagged: number;
    rules: Record<string, string>;
    enabled: boolean;
  }>(`/api/connections/${name}/detect-and-save-pii`, { method: "POST" });

// BYOK Key Management
export type BYOKKey = {
  id: string;
  org_id: string;
  key_alias: string;
  provider_type: string;
  provider_config: Record<string, unknown> | null;
  status: string;
  created_at: number;
  revoked_at: number | null;
};
export type BYOKStatus = {
  total: number;
  byok: number;
  managed: number;
  status: "none" | "partial" | "complete";
};
export const listBYOKKeys = () => request<BYOKKey[]>("/api/byok/keys");
export const createBYOKKey = (body: {
  key_alias: string;
  provider_type: string;
  provider_config?: Record<string, unknown>;
}) =>
  request<BYOKKey>("/api/byok/keys", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const deleteBYOKKey = (keyId: string, force = false) =>
  request<void>(`/api/byok/keys/${keyId}${force ? "?force=true" : ""}`, {
    method: "DELETE",
  });
export const validateBYOKKey = (keyId: string) =>
  request<{ valid: boolean; error?: string }>(
    `/api/byok/keys/${keyId}/validate`,
    { method: "POST" },
  );
export const getBYOKStatus = () => request<BYOKStatus>("/api/byok/status");
export const migrateToBYOK = (keyId: string) =>
  request<{ migrated: number; failed: number; errors: string[] }>(
    "/api/byok/migrate",
    { method: "POST", body: JSON.stringify({ key_id: keyId }) },
  );
export const revertToManaged = () =>
  request<{ migrated: number; failed: number; errors: string[] }>(
    "/api/byok/revert",
    { method: "POST" },
  );

// The following function clears the schema cache.
export const getSchemaCache = () =>
  request<{
    cached_connections: number;
    total_entries: number;
    ttl_seconds: number;
  }>("/api/schema-cache/stats");
export const invalidateSchemaCache = (name?: string) =>
  request<{ invalidated: number }>(
    `/api/schema-cache/invalidate${name ? `?connection_name=${encodeURIComponent(name)}` : ""}`,
    { method: "POST" },
  );

// The following function warms schemas for all connections in parallel.
export const warmupSchemas = () =>
  request<{
    warmed: number;
    total_connections: number;
    total_tables: number;
    results: {
      name: string;
      status: string;
      table_count?: number;
      error?: string;
    }[];
    duration_ms: number;
  }>("/api/connections/schema/warmup", { method: "POST" });

// Connection URL Validation
export const validateConnectionUrl = (
  connection_string: string,
  db_type: string,
) =>
  request<{
    valid: boolean;
    parsed?: Record<string, unknown>;
    warnings?: string[];
    error?: string;
  }>("/api/connections/validate-url", {
    method: "POST",
    body: JSON.stringify({ connection_string, db_type }),
  });

// The following function tests a connection before save.
export const testCredentials = (payload: Record<string, unknown>) =>
  request<{
    status: string;
    message: string;
    phases: {
      phase: string;
      status: string;
      message: string;
      hint?: string;
      duration_ms: number;
    }[];
    total_duration_ms?: number;
  }>("/api/connections/test-credentials", {
    method: "POST",
    body: JSON.stringify(payload),
  });

// The following function parses a connection URL into credential fields.
export const parseConnectionUrl = (url: string, db_type?: string) =>
  request<Record<string, string | number | boolean>>(
    "/api/connections/parse-url",
    { method: "POST", body: JSON.stringify({ url, db_type }) },
  );

// The following function returns connector capabilities.
export const getConnectorCapabilities = (dbType?: string) =>
  request<{
    tier_1?: {
      db_type: string;
      tier: number;
      label: string;
      feature_score: number;
    }[];
    tier_2?: {
      db_type: string;
      tier: number;
      label: string;
      feature_score: number;
    }[];
    tier_3?: {
      db_type: string;
      tier: number;
      label: string;
      feature_score: number;
    }[];
    total_connectors?: number;
    db_type?: string;
    tier?: number;
    label?: string;
    feature_score?: number;
    features?: Record<string, boolean>;
  }>(
    dbType
      ? `/api/connectors/capabilities?db_type=${encodeURIComponent(dbType)}`
      : "/api/connectors/capabilities",
  );

export const getConnectionCapabilities = (name: string) =>
  request<{
    connection_name: string;
    db_type: string;
    tier: number;
    tier_label: string;
    feature_score: number;
    features: Record<string, boolean>;
    configured: Record<string, boolean>;
  }>(`/api/connections/${name}/capabilities`);

// The following function returns network information for IP allowlists.
export const getNetworkInfo = () =>
  request<{
    hostname: string;
    local_ips: string[];
    public_ip: string | null;
    whitelist_instructions: Record<string, string>;
  }>("/api/network/info");

// The following function returns DNS, TCP, TLS, and authentication diagnostics.
export const diagnoseConnection = (name: string) =>
  request<{
    host: string;
    port: number;
    diagnostics: {
      check: string;
      status: string;
      message: string;
      hint?: string;
      duration_ms: number;
    }[];
  }>(`/api/connections/${name}/diagnose`, { method: "POST" });

// The following functions support semantic model editing.
export const getSemanticModel = (name: string) =>
  request<{
    tables: Record<
      string,
      {
        description: string;
        columns: Record<
          string,
          { description?: string; business_name?: string; unit?: string }
        >;
      }
    >;
    joins: { from: string; to: string; type?: string; description?: string }[];
    glossary: Record<string, string>;
  }>(`/api/connections/${name}/semantic-model`);

export const updateSemanticModel = (
  name: string,
  model: Record<string, unknown>,
) =>
  request<Record<string, unknown>>(`/api/connections/${name}/semantic-model`, {
    method: "PUT",
    body: JSON.stringify(model),
  });

export const generateSemanticModel = (name: string) =>
  request<{
    tables: number;
    joins: number;
    glossary_terms: number;
    generated: {
      tables_with_descriptions: number;
      joins_added: number;
      glossary_terms_added: number;
    };
  }>(`/api/connections/${name}/semantic-model/generate`, { method: "POST" });

// The following function returns schema differences.
export const getConnectionSchemaDiff = (name: string) =>
  request<{
    connection_name: string;
    has_cached: boolean;
    table_count: number;
    diff?: {
      has_changes: boolean;
      added_tables: string[];
      removed_tables: string[];
      modified_tables: unknown[];
    };
    message?: string;
  }>(`/api/connections/${name}/schema/diff`);

// The following function returns schema DDL in the Spider 2.0 format.
export const getConnectionSchemaDDL = (name: string, maxTables = 50) =>
  request<{
    connection_name: string;
    format: string;
    table_count: number;
    token_estimate: number;
    ddl: string;
  }>(`/api/connections/${name}/schema/ddl?max_tables=${maxTables}`);

export const getConnectionSchemaLink = (
  name: string,
  question: string,
  format = "ddl",
  maxTables = 20,
) =>
  request<{
    connection_name: string;
    question: string;
    format: string;
    linked_tables: number;
    total_tables: number;
    token_estimate?: number;
    ddl?: string;
    schema?: string;
    scores?: Record<string, number>;
    tables?: Record<string, unknown>;
  }>(
    `/api/connections/${name}/schema/link?question=${encodeURIComponent(question)}&format=${format}&max_tables=${maxTables}`,
  );

// The following functions browse local DuckDB and SQLite files through the sandbox manager.
export const browseFiles = (path?: string, pattern = "*.duckdb") => {
  const params = new URLSearchParams({ pattern });
  if (path) params.set("path", path);
  return request<{
    path: string;
    files: { name: string; path: string; size_bytes: number }[];
    directories: { name: string; path: string }[];
    error?: string;
  }>(`/api/files/browse?${params}`);
};

// Knowledge Base
import type {
  KnowledgeDoc,
  KnowledgeEdit,
  KnowledgeUsage,
  RetrievalStats,
} from "./types";
import type {
  GitHubInstallation,
  GitHubRepo,
  GitHubRepoLink,
  GitHubRepoImportResult,
  GitCredentials,
  DbtMapInfo,
  DbtMapResponse,
} from "./types";

export const listKnowledge = (params?: {
  scope?: string;
  scope_ref?: string;
  category?: string;
  status?: string;
}) => {
  const qs = params
    ? new URLSearchParams(
        Object.entries(params).filter(([, v]) => v !== undefined) as [
          string,
          string,
        ][],
      ).toString()
    : "";
  return request<KnowledgeDoc[]>(`/api/knowledge${qs ? `?${qs}` : ""}`);
};
export const getKnowledgeUsage = () =>
  request<KnowledgeUsage>("/api/knowledge/usage");
export const getKnowledgeRetrievals = (sinceDays = 30) =>
  request<RetrievalStats>(`/api/knowledge/retrievals?since_days=${sinceDays}`);
export const getKnowledgeDoc = (id: string) =>
  request<KnowledgeDoc>(`/api/knowledge/${id}`);
export const createKnowledgeDoc = (payload: {
  scope: KnowledgeDoc["scope"];
  scope_ref: string | null;
  category: KnowledgeDoc["category"];
  title: string;
  body: string;
  status?: KnowledgeDoc["status"];
}) =>
  request<KnowledgeDoc>("/api/knowledge", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const updateKnowledgeDoc = (id: string, body: string) =>
  request<KnowledgeDoc>(`/api/knowledge/${id}`, {
    method: "PUT",
    body: JSON.stringify({ body }),
  });
export const archiveKnowledgeDoc = (id: string) =>
  request<void>(`/api/knowledge/${id}`, { method: "DELETE" });
export const approveKnowledgeDoc = (id: string) =>
  request<KnowledgeDoc>(`/api/knowledge/${id}/approve`, { method: "POST" });
export const listKnowledgeEdits = (id: string, limit = 20) =>
  request<KnowledgeEdit[]>(`/api/knowledge/${id}/edits?limit=${limit}`);

// The following functions support rendered HTML reports.
import type { Report, ReportSummary } from "./types";

export const listReports = (params?: { scope_ref?: string }) => {
  const qs = params?.scope_ref
    ? `?scope_ref=${encodeURIComponent(params.scope_ref)}`
    : "";
  return request<ReportSummary[]>(`/api/reports${qs}`);
};
export const getReport = (id: string) => request<Report>(`/api/reports/${id}`);
export const createReport = (payload: {
  title: string;
  html: string;
  scope_ref?: string | null;
}) =>
  request<Report>("/api/reports", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const deleteReport = (id: string) =>
  request<void>(`/api/reports/${id}`, { method: "DELETE" });

// Notion Integrations
export type NotionIntegration = {
  id: string;
  name: string;
  search_page_ids: string[];
  report_parent_page_id: string | null;
  status: string;
  created_at: number;
  org_id: string | null;
};
export type NotionOAuthInstallationConfig = {
  parent_page_id: string | null;
  trigger_page_id: string | null;
  requests_data_source_id: string | null;
  requests_database_page_id: string | null;
  enabled: boolean;
  default_project_id: string | null;
  default_branch: string;
  analysis_branch_mode: "per_request" | "default_branch";
};
export type NotionOAuthInstallation = {
  id: string;
  workspace_id: string;
  workspace_name: string | null;
  bot_id: string;
  owner_user_id: string | null;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  org_id: string | null;
  config: NotionOAuthInstallationConfig | null;
};
export type NotionPageOption = {
  id: string;
  title: string;
  url: string | null;
};
export type OrgSecretsResponse = {
  has_key: boolean;
  key_preview: string | null;
  updated_at: number | null;
};
export type OrgSecretsUpdate = {
  anthropic_api_key: string | null;
};
export const getOrgSecrets = () =>
  request<OrgSecretsResponse>("/api/org/secrets");
export const updateOrgSecrets = (payload: OrgSecretsUpdate) =>
  request<OrgSecretsResponse>("/api/org/secrets", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
export const getNotionIntegrations = () =>
  request<NotionIntegration[]>("/api/integrations/notion");
export const createNotionIntegration = (payload: {
  name: string;
  api_key: string;
  search_page_ids: string[];
  report_parent_page_id?: string;
}) =>
  request<NotionIntegration>("/api/integrations/notion", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const updateNotionIntegration = (
  name: string,
  updates: Record<string, unknown>,
) =>
  request<NotionIntegration>(`/api/integrations/notion/${name}`, {
    method: "PUT",
    body: JSON.stringify(updates),
  });
export const deleteNotionIntegration = (name: string) =>
  request<void>(`/api/integrations/notion/${name}`, { method: "DELETE" });
export const testNotionIntegration = (name: string) =>
  request<{ status: string; message: string }>(
    `/api/integrations/notion/${name}/test`,
    { method: "POST" },
  );
export const startNotionOAuth = (redirectAfter?: string) => {
  const qs = redirectAfter
    ? `?redirect_after=${encodeURIComponent(redirectAfter)}`
    : "";
  return request<{ authorize_url: string; state: string }>(
    `/api/integrations/notion/oauth/start${qs}`,
  );
};
export const getNotionOAuthInstallations = () =>
  request<NotionOAuthInstallation[]>(
    "/api/integrations/notion/oauth/installations",
  );
export const getNotionOAuthPages = (installationId: string, query?: string) => {
  const qs = query ? `?query=${encodeURIComponent(query)}` : "";
  return request<NotionPageOption[]>(
    `/api/integrations/notion/oauth/${installationId}/pages${qs}`,
  );
};
export type NotionProvisionPayload = {
  sibling_page_id?: string | null;
  parent_page_id?: string | null;
  default_project_id?: string | null;
  default_branch?: string;
  analysis_branch_mode?: "per_request" | "default_branch";
};
export const provisionNotionOAuthInstallation = (
  installationId: string,
  payload: NotionProvisionPayload | string | null = {},
) => {
  const body =
    typeof payload === "string" ? { parent_page_id: payload } : (payload ?? {});
  return request<{
    installation: NotionOAuthInstallation;
    trigger_page_id: string;
    requests_data_source_id: string;
    requests_database_page_id: string;
  }>(`/api/integrations/notion/oauth/${installationId}/provision`, {
    method: "POST",
    body: JSON.stringify(body),
  });
};
export const deleteNotionOAuthInstallation = (installationId: string) =>
  request<void>(`/api/integrations/notion/oauth/${installationId}`, {
    method: "DELETE",
  });

// The following functions support Slack integrations.
export type SlackOAuthInstallationConfig = {
  enabled: boolean;
  default_project_id: string | null;
  default_branch: string;
  analysis_branch_mode: "per_request" | "default_branch";
  allowed_channel_ids: string[];
};
export type SlackOAuthInstallation = {
  id: string;
  team_id: string;
  team_name: string | null;
  enterprise_id: string | null;
  enterprise_name: string | null;
  app_id: string | null;
  bot_user_id: string;
  authed_user_id: string | null;
  scopes: string[];
  status: string;
  created_at: string | null;
  updated_at: string | null;
  org_id: string | null;
  config: SlackOAuthInstallationConfig | null;
};
export const startSlackOAuth = (redirectAfter?: string) => {
  const qs = redirectAfter
    ? `?redirect_after=${encodeURIComponent(redirectAfter)}`
    : "";
  return request<{ authorize_url: string; state: string }>(
    `/api/integrations/slack/oauth/start${qs}`,
  );
};
export const getSlackOAuthInstallations = () =>
  request<SlackOAuthInstallation[]>(
    "/api/integrations/slack/oauth/installations",
  );
export type SlackProvisionPayload = {
  default_project_id: string;
  default_branch?: string;
  analysis_branch_mode?: "per_request" | "default_branch";
  allowed_channel_ids?: string[];
};
export const provisionSlackOAuthInstallation = (
  installationId: string,
  payload: SlackProvisionPayload,
) =>
  request<{ installation: SlackOAuthInstallation }>(
    `/api/integrations/slack/oauth/${installationId}/provision`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
export const deleteSlackOAuthInstallation = (installationId: string) =>
  request<void>(`/api/integrations/slack/oauth/${installationId}`, {
    method: "DELETE",
  });

// Metrics SSE (uses fetch instead of EventSource so we can send auth headers)
export function subscribeMetrics(
  cb: (data: import("./types").MetricsSnapshot) => void,
): () => void {
  let aborted = false;
  const controller = new AbortController();

  (async () => {
    // Wait for authentication before each connection attempt.
    for (let attempt = 0; attempt < 10 && !aborted; attempt++) {
      const authHeader = await _getAuthHeader();
      if (!authHeader) {
        // Wait and retry while Clerk loads.
        await new Promise((r) => setTimeout(r, 1000));
        continue;
      }

      try {
        const res = await fetch(`${GATEWAY_URL}/api/metrics`, {
          headers: { Accept: "text/event-stream", Authorization: authHeader },
          signal: controller.signal,
        });
        if (res.status === 401 || res.status === 403) {
          // Retry when the token is expired or unavailable.
          await new Promise((r) => setTimeout(r, 2000));
          continue;
        }
        if (!res.ok || !res.body) return;

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";

        while (!aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";
          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                cb(JSON.parse(line.slice(6)) as any);
              } catch {}
            }
          }
        }
        return; // Clean exit
      } catch {
        if (aborted) return;
        await new Promise((r) => setTimeout(r, 2000));
      }
    }
  })();

  return () => {
    aborted = true;
    controller.abort();
  };
}
