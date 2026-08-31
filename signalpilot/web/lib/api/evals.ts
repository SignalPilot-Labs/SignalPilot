// Evaluation runs, sandboxes, accuracy, and artifacts for the /evals pages.

import {
  GATEWAY_URL,
  _getAuthHeader,
  getAuthHeaders,
  request,
} from "./client";

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
export type EvalGradeExpectation = {
  name: string;
  value?: number;
  tolerance?: number;
};
export type EvalGrade = {
  kind: "checks" | "model_rebuilt";
  expectations?: EvalGradeExpectation[];
} & Record<string, unknown>;
export type EvalCaptureSpec = {
  tables: string[];
  mode: string;
  sample_rows: number;
};
export type EvalCaptureResult = {
  row_count?: number;
  grain_unique?: boolean;
  stored?: string[];
} & Record<string, unknown>;
export type EvalCoverageLayer = {
  total?: number;
  covered?: number;
  pct?: number | null;
};
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
export function evalSandboxName(
  ref: EvalSandboxRef | undefined,
): string | null {
  if (!ref) return null;
  return typeof ref === "string" ? ref : (ref.name ?? null);
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
export const getEvalAvailability = () =>
  request<EvalAvailability>("/api/evals/availability");

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

export const listEvalSandboxes = () =>
  request<EvalSandboxInventory>("/api/evals/sandboxes");
export const getEvalSandboxEvents = (name: string) =>
  request<{
    backend: string;
    supported: boolean;
    message: string;
    events: EvalSandboxEvent[];
  }>(`/api/evals/sandboxes/${encodeURIComponent(name)}/events`);
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
        cb({
          type: "end",
          reason: `http-${res.status}`,
          at: Date.now() / 1000,
        });
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
          try {
            cb(JSON.parse(line.slice(6)) as EvalLogEvent);
          } catch {}
        }
      }
    } catch {
      if (!aborted)
        cb({ type: "end", reason: "disconnected", at: Date.now() / 1000 });
    }
  })();

  return () => {
    aborted = true;
    controller.abort();
  };
}

export async function getEvalTranscript(
  runId: string,
  taskId: string,
): Promise<string> {
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
export const evalArtifactUrl = (
  runId: string,
  taskId: string,
  filename: string,
) =>
  `${GATEWAY_URL}/api/evals/runs/${runId}/artifacts/${encodeURIComponent(taskId)}/${encodeURIComponent(filename)}`;
export const evalExportUrl = (runId: string) =>
  `${GATEWAY_URL}/api/evals/runs/${runId}/export`;

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
export const downloadEvalArtifact = (
  runId: string,
  taskId: string,
  filename: string,
) => downloadAuthed(evalArtifactUrl(runId, taskId, filename), filename);
export const downloadEvalRunExport = (runId: string) =>
  downloadAuthed(evalExportUrl(runId), `eval-${runId}.zip`);
