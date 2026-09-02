import type { StandaloneChatEvent } from "~/lib/api";

/**
 * Folds the raw standalone-chat run event stream into a compact list of
 * renderable "steps" for the agent activity timeline. Pure and synchronous so
 * it can be unit tested and replayed deterministically on the fixture page.
 */

export type RunStepCategory =
  | "sql"
  | "python"
  | "notebook"
  | "terminal"
  | "file-write"
  | "file-edit"
  | "file-read"
  | "todo"
  | "web"
  | "source"
  | "artifact"
  | "dashboard"
  | "dbt"
  | "plan"
  | "approval"
  | "progress"
  | "subagent"
  | "error"
  | "generic";

export type RunStepStatus = "running" | "succeeded" | "failed" | "info";

export type RunStep = {
  /** Stable key for React rendering. */
  key: string;
  sequence: number;
  category: RunStepCategory;
  status: RunStepStatus;
  /** Human title, e.g. "Queried the warehouse". */
  title: string;
  /** Normalized tool name without the mcp__server__ prefix, if a tool step. */
  tool: string | null;
  /** Which MCP server the tool came from, or "claude-code" for base tools. */
  toolOrigin: "signalpilot" | "notebook" | "chat" | "claude-code" | null;
  input: Record<string, unknown> | null;
  /** SQL attached via the dedicated `sql` event or found in the tool input. */
  sql: string | null;
  /** Python source when the tool executes code. */
  code: string | null;
  /** File path or artifact filename this step produced or touched. */
  file: string | null;
  /** Schema/model/metric reference chips. */
  sources: string[];
  /** Free-form detail line (progress label, completion summary, error). */
  detail: string | null;
  startedAt: string;
  endedAt: string | null;
  durationMs: number | null;
  /** Subagent spawns only: the child steps executed inside the subagent. */
  children: RunStep[];
  /** Subagent spawns only: the agent type (e.g. "Explore"). */
  subagentType: string | null;
  /** Subagent spawns only: the final report the subagent returned. */
  report: string | null;
  /** Subagent spawns only: the subagent's streamed narration so far. */
  liveText: string;
  /** Sanitized support data present only on terminal run errors. */
  fullTrace?: string | null;
  diagnostics?: Record<string, unknown> | null;
};

export type RunStepSummary = {
  total: number;
  queries: number;
  codeRuns: number;
  files: number;
  errors: number;
  running: boolean;
};

export function formatErrorSupportBundle(step: RunStep): string {
  const diagnostics = step.diagnostics
    ? Object.entries(step.diagnostics).map(
        ([key, value]) =>
          `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`,
      )
    : [];
  return [
    step.detail ? `Root cause: ${step.detail}` : "",
    diagnostics.length ? `Diagnostics:\n${diagnostics.join("\n")}` : "",
    step.fullTrace ? `Full trace:\n${step.fullTrace}` : "",
  ]
    .filter(Boolean)
    .join("\n\n");
}

const SQL_TOOLS = new Set([
  "query_database",
  "explain_query",
  "validate_sql",
  "plan_query",
  "preview_query",
]);
const PYTHON_TOOLS = new Set(["run_cells"]);
const NOTEBOOK_TOOLS = new Set([
  "start_analysis_notebook",
  "edit_notebook",
  "save_data_snapshot",
]);
const FILE_WRITE_TOOLS = new Set(["Write", "NotebookEdit"]);
const FILE_EDIT_TOOLS = new Set(["Edit", "MultiEdit"]);
const FILE_READ_TOOLS = new Set(["Read", "Glob", "Grep", "LS"]);
const WEB_TOOLS = new Set(["WebFetch", "WebSearch"]);
const ARTIFACT_TOOLS = new Set([
  "publish_table",
  "publish_chart",
  "publish_report",
]);

export function normalizeToolName(raw: string): {
  tool: string;
  origin: RunStep["toolOrigin"];
} {
  const match = /^mcp__([^_]+(?:[-_][^_]+)*?)__(.+)$/.exec(raw);
  if (!match) return { tool: raw, origin: "claude-code" };
  const server = match[1];
  const tool = match[2];
  if (server.includes("notebook")) return { tool, origin: "notebook" };
  if (server.includes("standalone") || server.includes("chat")) {
    return { tool, origin: "chat" };
  }
  return { tool, origin: "signalpilot" };
}

function categorizeTool(tool: string): RunStepCategory {
  if (tool === "create_dashboard_preview") return "dashboard";
  if (SQL_TOOLS.has(tool)) return "sql";
  if (PYTHON_TOOLS.has(tool)) return "python";
  if (NOTEBOOK_TOOLS.has(tool)) return "notebook";
  if (tool === "Bash" || tool.startsWith("sandbox_")) return "terminal";
  if (FILE_WRITE_TOOLS.has(tool)) return "file-write";
  if (FILE_EDIT_TOOLS.has(tool)) return "file-edit";
  if (FILE_READ_TOOLS.has(tool)) return "file-read";
  if (tool === "TodoWrite") return "todo";
  if (WEB_TOOLS.has(tool)) return "web";
  if (ARTIFACT_TOOLS.has(tool)) return "artifact";
  if (tool === "inspect_dbt" || tool.startsWith("dbt_")) return "dbt";
  if (/schema|table|column|relationship|metric|model|source|lineage/.test(tool)) {
    return "source";
  }
  return "generic";
}

function humanizeTool(tool: string): string {
  const titles: Record<string, string> = {
    query_database: "Queried the warehouse",
    explain_query: "Explained query plan",
    validate_sql: "Validated SQL",
    plan_query: "Planned the query",
    run_cells: "Executed notebook cells",
    edit_notebook: "Edited the analysis notebook",
    start_analysis_notebook: "Started the analysis notebook",
    save_data_snapshot: "Saved a data snapshot",
    inspect_dbt: "Inspected the dbt project",
    dbt_execute: "Ran dbt against the warehouse",
    sandbox_exec: "Ran a command in the sandbox",
    sandbox_write_file: "Wrote a file in the sandbox",
    sandbox_read_file: "Read a file in the sandbox",
    publish_table: "Published a table",
    publish_chart: "Published a chart",
    publish_report: "Published a report",
    create_dashboard_preview: "Creating dashboard preview",
    Bash: "Ran a command",
    Write: "Generated a file",
    Edit: "Edited a file",
    MultiEdit: "Edited a file",
    Read: "Read a file",
    Glob: "Searched for files",
    Grep: "Searched file contents",
    TodoWrite: "Updated the plan",
    WebFetch: "Fetched a page",
    WebSearch: "Searched the web",
  };
  if (titles[tool]) return titles[tool];
  return tool
    .replaceAll("_", " ")
    .replace(/^[a-z]/, (letter) => letter.toUpperCase());
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

/** The proxy's sign-in error; the transcript shows a card for it instead. */
const CONNECTOR_NEEDS_SIGN_IN = /needs you to sign in/i;

function chatToolSummary(value: unknown): string | null {
  return text(value)?.replace(/\bgoverned tool\b/gi, "tool") ?? null;
}

function extractFile(
  tool: string,
  category: RunStepCategory,
  input: Record<string, unknown> | null,
): string | null {
  if (!input) return null;
  const candidate =
    text(input.file_path) ??
    text(input.filename) ??
    text(input.path) ??
    text(input.notebook_path) ??
    (category === "file-read" ? text(input.pattern) : null);
  if (candidate) return candidate;
  if (tool === "WebFetch" || tool === "WebSearch") {
    return text(input.url) ?? text(input.query);
  }
  return null;
}

function extractCode(
  tool: string,
  input: Record<string, unknown> | null,
): string | null {
  if (!input) return null;
  if (tool === "Bash") return text(input.command);
  if (tool === "Write" || tool === "NotebookEdit") {
    return text(input.content) ?? text(input.new_source);
  }
  if (tool === "run_cells" || tool === "edit_notebook") {
    const cells = Array.isArray(input.cells) ? input.cells : null;
    if (cells) {
      const sources = cells
        .map((cell) => {
          const record = asRecord(cell);
          return (
            text(record?.source) ??
            text(record?.code) ??
            (typeof cell === "string" ? cell : null)
          );
        })
        .filter((value): value is string => Boolean(value));
      if (sources.length) return sources.join("\n\n");
    }
    return text(input.source) ?? text(input.code);
  }
  return null;
}

function extractSources(input: Record<string, unknown> | null): string[] {
  if (!input) return [];
  const keys = [
    "metric_name",
    "model_name",
    "schema_name",
    "source_name",
    "table_name",
  ];
  return keys
    .map((key) => text(input[key]))
    .filter((value): value is string => Boolean(value));
}

/** Fresh per-step defaults for the subagent fields (never share the array). */
function emptyStepExtras(): Pick<
  RunStep,
  "children" | "subagentType" | "report" | "liveText"
> {
  return { children: [], subagentType: null, report: null, liveText: "" };
}

/** Tool names that spawn a subagent whose work is grouped under the spawn. */
const SUBAGENT_SPAWN_TOOLS = new Set(["Agent", "Task"]);

const durationBetween = (start: string, end: string): number | null => {
  const startMs = Date.parse(start);
  const endMs = Date.parse(end);
  return Number.isFinite(startMs) && Number.isFinite(endMs)
    ? Math.max(0, endMs - startMs)
    : null;
};

export function foldRunSteps(
  events: StandaloneChatEvent[],
  runId: string,
): RunStep[] {
  const steps: RunStep[] = [];
  /** Open tool steps awaiting their tool_completed, in start order (fallback
   * when no tool_call_id is present). Subagent children never join this
   * queue — they pair strictly by tool_call_id so parallel subagents cannot
   * steal a top-level completion. */
  const open: RunStep[] = [];
  /** Open steps keyed by tool_call_id — the reliable pairing when present. */
  const openById = new Map<string, RunStep>();
  /** Subagent spawn steps keyed by the Agent tool_call_id. */
  const subagentsById = new Map<string, RunStep>();
  const runEvents = events
    .filter((event) => event.run_id === runId)
    .sort((a, b) => a.sequence - b.sequence);

  for (const event of runEvents) {
    const key = `${event.run_id}-${event.sequence}`;
    if (event.type === "tool_started") {
      const rawTool = text(event.payload.tool) ?? "analysis tool";
      const { tool, origin } = normalizeToolName(rawTool);
      const toolCallId = text(event.payload.tool_call_id);
      const parentId = text(event.payload.parent_tool_call_id);
      const input = asRecord(event.payload.input);
      const isSpawn = SUBAGENT_SPAWN_TOOLS.has(tool);
      const category = isSpawn ? "subagent" : categorizeTool(tool);
      const step: RunStep = {
        key,
        sequence: event.sequence,
        category,
        status: "running",
        title: isSpawn
          ? (text(input?.description) ?? "Subagent")
          : humanizeTool(tool),
        tool,
        toolOrigin: origin,
        input,
        sql:
          category === "sql"
            ? (text(input?.sql) ?? text(input?.query))
            : null,
        code: extractCode(tool, input),
        file: extractFile(tool, category, input),
        sources: extractSources(input),
        detail: null,
        startedAt: event.created_at,
        endedAt: null,
        durationMs: null,
        ...emptyStepExtras(),
        subagentType: isSpawn ? text(input?.subagent_type) : null,
      };
      const parent = parentId ? subagentsById.get(parentId) : undefined;
      if (parent) {
        parent.children.push(step);
      } else {
        // Top level (or an orphaned child from a legacy event stream —
        // degrade to the flat rendering rather than dropping it).
        steps.push(step);
        open.push(step);
      }
      if (toolCallId) openById.set(toolCallId, step);
      if (isSpawn && toolCallId) subagentsById.set(toolCallId, step);
      continue;
    }
    if (event.type === "tool_completed") {
      // Pair by tool_call_id when the worker provides it (tools can complete
      // out of order); fall back to FIFO only when it's absent.
      const toolCallId = text(event.payload.tool_call_id);
      let step: RunStep | undefined;
      if (toolCallId && openById.has(toolCallId)) {
        step = openById.get(toolCallId);
        openById.delete(toolCallId);
        const idx = open.indexOf(step!);
        if (idx >= 0) open.splice(idx, 1);
      } else {
        step = open.shift();
      }
      if (!step) continue;
      const failed = event.payload.error === true;
      step.status = failed ? "failed" : "succeeded";
      step.endedAt = event.created_at;
      step.durationMs = durationBetween(step.startedAt, event.created_at);
      if (step.category === "subagent") {
        step.report = text(event.payload.report);
      }
      if (failed) {
        // The worker writes the failure text as `summary`; `message` is the
        // legacy field kept as a fallback.
        const failure =
          chatToolSummary(event.payload.summary) ??
          chatToolSummary(event.payload.message) ??
          "The tool returned an error.";
        if (CONNECTOR_NEEDS_SIGN_IN.test(failure)) {
          // A connector sign-in card renders for this run (see
          // chat-connector-signin.ts); the row says it once, quietly, and
          // never repeats the agent-facing error text.
          step.title = `${step.title} · needs sign-in`;
          step.detail = null;
        } else {
          step.detail = failure;
        }
      }
      continue;
    }
    if (event.type === "text_delta") {
      // Subagent narration streams tagged with its spawn id; surface it as
      // the live line on the subagent card. Main narration is handled by
      // foldRunBlocks.
      const parentId = text(event.payload.parent_tool_call_id);
      const delta = event.payload.delta;
      if (parentId && typeof delta === "string") {
        const parent = subagentsById.get(parentId);
        if (parent) parent.liveText += delta;
      }
      continue;
    }
    if (event.type === "sql") {
      const sql = text(event.payload.sql);
      if (!sql) continue;
      const target =
        open.find((step) => step.category === "sql" && !step.sql) ??
        open.find((step) => step.category === "sql");
      if (target) {
        target.sql = target.sql ?? sql;
        continue;
      }
      steps.push({
        key,
        sequence: event.sequence,
        category: "sql",
        status: "info",
        title: "Proposed SQL",
        tool: null,
        toolOrigin: null,
        input: null,
        sql,
        code: null,
        file: null,
        sources: [],
        detail: null,
        startedAt: event.created_at,
        endedAt: event.created_at,
        durationMs: null,
        ...emptyStepExtras(),
      });
      continue;
    }
    if (event.type === "source") {
      const refs = extractSources(asRecord(event.payload));
      if (!refs.length) continue;
      const target = open[open.length - 1];
      if (target) {
        for (const ref of refs) {
          if (!target.sources.includes(ref)) target.sources.push(ref);
        }
      }
      continue;
    }
    if (event.type === "progress") {
      const label = text(event.payload.label);
      if (!label) continue;
      if (text(event.payload.scope) === "dashboard_authoring") {
        const dashboardStep = [...open]
          .reverse()
          .find((step) => step.tool === "create_dashboard_preview");
        if (dashboardStep) {
          dashboardStep.detail = label;
          continue;
        }
      }
      steps.push({
        key,
        sequence: event.sequence,
        category: "progress",
        status: "info",
        title: label,
        tool: null,
        toolOrigin: null,
        input: null,
        sql: null,
        code: null,
        file: null,
        sources: [],
        detail: null,
        startedAt: event.created_at,
        endedAt: event.created_at,
        durationMs: null,
        ...emptyStepExtras(),
      });
      continue;
    }
    if (event.type === "plan_created") {
      const rows = event.payload.estimated_output_rows;
      const rowsLabel =
        typeof rows === "number" && rows > 0
          ? ` (~${rows.toLocaleString()} rows)`
          : "";
      steps.push({
        key,
        sequence: event.sequence,
        category: "plan",
        status: "info",
        title: `Planned a governed query${rowsLabel}`,
        tool: null,
        toolOrigin: null,
        input: null,
        sql: text(event.payload.sql),
        code: null,
        file: null,
        sources: [],
        detail: text(event.payload.purpose),
        startedAt: event.created_at,
        endedAt: event.created_at,
        durationMs: null,
        ...emptyStepExtras(),
      });
      continue;
    }
    if (event.type === "route_selected") {
      const route = text(event.payload.route) ?? "analysis";
      const routeTitles: Record<string, string> = {
        mcp: "Route: run it as a direct governed query",
        notebook_sdk: "Route: open a notebook for deeper analysis",
        dataset_ref: "Route: reference the governed dataset",
        aggregate_required: "Route: too broad — needs a bounded aggregate",
        refuse: "Route: refused by governance",
      };
      steps.push({
        key,
        sequence: event.sequence,
        category: "plan",
        status: route === "refuse" ? "failed" : "info",
        title: routeTitles[route] ?? `Route: ${route}`,
        tool: null,
        toolOrigin: null,
        input: null,
        sql: null,
        code: null,
        file: null,
        sources: [],
        detail: null,
        startedAt: event.created_at,
        endedAt: event.created_at,
        durationMs: null,
        ...emptyStepExtras(),
      });
      continue;
    }
    if (event.type === "cell_executed") {
      const failed = event.payload.status === "failed";
      const target = [...steps]
        .reverse()
        .find(
          (step) => step.tool === "run_cells" || step.category === "python",
        );
      if (target && failed && target.status !== "failed") {
        target.status = "failed";
        target.detail = "A notebook cell failed to execute.";
      }
      continue;
    }
    if (
      event.type === "query_approval_requested" ||
      event.type === "query_approved" ||
      event.type === "query_declined"
    ) {
      steps.push({
        key,
        sequence: event.sequence,
        category: "approval",
        status:
          event.type === "query_declined"
            ? "failed"
            : event.type === "query_approved"
              ? "succeeded"
              : "running",
        title:
          event.type === "query_approval_requested"
            ? "Waiting for query approval"
            : event.type === "query_approved"
              ? "Query approved"
              : "Query declined",
        tool: null,
        toolOrigin: null,
        input: null,
        sql: null,
        code: null,
        file: null,
        sources: [],
        detail: text(event.payload.purpose),
        startedAt: event.created_at,
        endedAt: event.created_at,
        durationMs: null,
        ...emptyStepExtras(),
      });
      continue;
    }
    if (event.type === "error") {
      steps.push({
        key,
        sequence: event.sequence,
        category: "error",
        status: "failed",
        title: "Run error",
        tool: null,
        toolOrigin: null,
        input: null,
        sql: null,
        code: null,
        file: null,
        sources: [],
        detail: text(event.payload.message),
        startedAt: event.created_at,
        endedAt: event.created_at,
        durationMs: null,
        fullTrace: text(event.payload.full_trace),
        diagnostics: asRecord(event.payload.diagnostic_context),
        ...emptyStepExtras(),
      });
      continue;
    }
  }
  // Approval requests are resolved by a later approved/declined step.
  for (const step of steps) {
    if (step.category === "approval" && step.status === "running") {
      const resolved = steps.some(
        (other) =>
          other.category === "approval" &&
          other.sequence > step.sequence &&
          other.status !== "running",
      );
      if (resolved) step.status = "info";
    }
  }
  return steps;
}

/** Current real server-side phase for a running dashboard preview tool. */
export type DashboardAuthoringProgress = {
  label: string;
  phase: string;
  sessionId: string | null;
  draftRevision: number;
};

export function activeDashboardAuthoringProgress(
  events: StandaloneChatEvent[],
  runId: string | undefined,
): DashboardAuthoringProgress | null {
  if (!runId) return null;
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (
      event.run_id !== runId ||
      event.type !== "progress" ||
      event.payload.scope !== "dashboard_authoring"
    ) {
      continue;
    }
    const label = event.payload.label;
    if (typeof label !== "string" || !label) return null;
    const phase = event.payload.phase;
    const sessionId = event.payload.authoring_session_id;
    const draftRevision = event.payload.draft_revision;
    return {
      label,
      phase: typeof phase === "string" ? phase : "",
      sessionId: typeof sessionId === "string" && sessionId ? sessionId : null,
      draftRevision: typeof draftRevision === "number" ? draftRevision : 0,
    };
  }
  return null;
}

export function activeDashboardPreviewLabel(
  events: StandaloneChatEvent[],
  runId: string | undefined,
): string | null {
  if (!runId) return null;
  const active = [...foldRunSteps(events, runId)]
    .reverse()
    .find(
      (step) =>
        step.tool === "create_dashboard_preview" && step.status === "running",
    );
  return (
    active?.detail ?? (active ? "Preparing governed dashboard preview" : null)
  );
}

export type RunBlock =
  | { kind: "text"; key: string; text: string }
  | { kind: "thinking"; key: string; text: string }
  | { kind: "steps"; key: string; steps: RunStep[] };

/**
 * Infers the quiet gap after a tool finishes while the run is still active.
 * This drives a presence indicator only; it never fabricates thought text.
 */
export function shouldShowAgentThinking(
  blocks: RunBlock[],
  running: boolean,
): boolean {
  if (!running) return false;
  const trailing = blocks.at(-1);
  if (!trailing) return true;
  return (
    trailing.kind === "steps" &&
    !trailing.steps.some((step) => step.status === "running")
  );
}

export type RuntimeBootPhase = "provisioning" | "resuming" | "ready";

export type RuntimeBootState = {
  phase: RuntimeBootPhase;
  startedAt: string;
  readyAt: string | null;
  bootMs: number | null;
};

/** Never leave an unresolved cold-boot card in a terminal transcript. */
export function shouldShowRuntimeBoot(
  boot: RuntimeBootState | null,
  running: boolean,
): boolean {
  return Boolean(boot && (running || boot.phase === "ready"));
}

/**
 * Extracts the sandbox boot lifecycle for a run from its `runtime_boot`
 * events. Returns null when the run reused a warm sandbox (no boot events),
 * which is exactly when the boot UI should not render.
 */
export function extractRuntimeBoot(
  events: StandaloneChatEvent[],
  runId: string,
): RuntimeBootState | null {
  let state: RuntimeBootState | null = null;
  for (const event of events) {
    if (event.run_id !== runId || event.type !== "runtime_boot") continue;
    const phase = text(event.payload.phase) as RuntimeBootPhase | null;
    if (!phase) continue;
    if (phase === "ready") {
      if (state) {
        state.phase = "ready";
        state.readyAt = event.created_at;
        const ms = event.payload.boot_ms;
        state.bootMs = typeof ms === "number" && ms >= 0 ? ms : null;
      }
      continue;
    }
    if (state) {
      // A snapshot resume can fall back to a fresh provision; keep the
      // original start time but show the latest real phase.
      state.phase = phase;
    } else {
      state = { phase, startedAt: event.created_at, readyAt: null, bootMs: null };
    }
  }
  return state;
}

export type PlanItemStatus = "pending" | "in_progress" | "completed";

export type PlanItem = {
  content: string;
  /** Present-tense label shown while the item is in progress. */
  activeForm: string | null;
  status: PlanItemStatus;
};

export type RunPlan = {
  items: PlanItem[];
  completed: number;
  /** The in-progress item, preferring its activeForm for display. */
  currentLabel: string | null;
  /** Sequence of the TodoWrite event the plan came from. */
  sequence: number;
};

/**
 * The latest plan the agent published via TodoWrite, for the pinned plan
 * tracker. Subagent TodoWrites are ignored — the tracker shows the main
 * run's plan only. Returns null until the run publishes a plan.
 */
export function extractRunPlan(
  events: StandaloneChatEvent[],
  runId: string,
): RunPlan | null {
  let latest: { sequence: number; input: Record<string, unknown> } | null =
    null;
  for (const event of events) {
    if (event.run_id !== runId || event.type !== "tool_started") continue;
    if (text(event.payload.parent_tool_call_id)) continue;
    const rawTool = text(event.payload.tool);
    if (!rawTool || normalizeToolName(rawTool).tool !== "TodoWrite") continue;
    const input = asRecord(event.payload.input);
    if (!input) continue;
    if (!latest || event.sequence > latest.sequence) {
      latest = { sequence: event.sequence, input };
    }
  }
  if (!latest) return null;
  const todos = Array.isArray(latest.input.todos) ? latest.input.todos : [];
  const items: PlanItem[] = [];
  for (const todo of todos) {
    const record = asRecord(todo);
    const content = text(record?.content);
    if (!content) continue;
    const status = text(record?.status);
    items.push({
      content,
      activeForm: text(record?.activeForm),
      status:
        status === "completed" || status === "in_progress"
          ? status
          : "pending",
    });
  }
  if (!items.length) return null;
  const current = items.find((item) => item.status === "in_progress") ?? null;
  return {
    items,
    completed: items.filter((item) => item.status === "completed").length,
    currentLabel: current ? (current.activeForm ?? current.content) : null,
    sequence: latest.sequence,
  };
}

/**
 * Reconstructs the natural interleaving of an agent run: contiguous streamed
 * text becomes a markdown block, contiguous tool work becomes a step group.
 * A run that narrates between tool chains therefore renders as
 * [steps] → [text] → [steps] → [text] in stream order.
 */
export function foldRunBlocks(
  events: StandaloneChatEvent[],
  runId: string,
): RunBlock[] {
  const steps = foldRunSteps(events, runId);
  const stepsBySequence = new Map(steps.map((step) => [step.sequence, step]));
  const runEvents = events
    .filter((event) => event.run_id === runId)
    .sort((a, b) => a.sequence - b.sequence);
  const blocks: RunBlock[] = [];
  let textBuffer = "";
  let textKey = "";
  let thinkingBuffer = "";
  let thinkingKey = "";
  const flushText = () => {
    if (!textBuffer.trim()) {
      textBuffer = "";
      return;
    }
    blocks.push({ kind: "text", key: `text-${textKey}`, text: textBuffer });
    textBuffer = "";
  };
  const flushThinking = () => {
    if (!thinkingBuffer.trim()) {
      thinkingBuffer = "";
      return;
    }
    blocks.push({
      kind: "thinking",
      key: `thinking-${thinkingKey}`,
      text: thinkingBuffer,
    });
    thinkingBuffer = "";
  };
  for (const event of runEvents) {
    // Subagent-internal streams belong to their spawn card, never to the
    // run's own narration or thinking.
    if (
      (event.type === "text_delta" || event.type === "thinking_delta") &&
      text(event.payload.parent_tool_call_id)
    ) {
      continue;
    }
    if (event.type === "text_delta") {
      flushThinking();
      const delta = event.payload.delta;
      if (typeof delta === "string") {
        if (!textBuffer) textKey = `${event.run_id}-${event.sequence}`;
        textBuffer += delta;
      }
      continue;
    }
    if (event.type === "thinking_delta") {
      flushText();
      const delta = event.payload.delta;
      if (typeof delta === "string") {
        if (!thinkingBuffer) thinkingKey = `${event.run_id}-${event.sequence}`;
        thinkingBuffer += delta;
      }
      continue;
    }
    if (
      event.type === "status" &&
      event.payload.reset_text === true
    ) {
      // A retry restarted the answer: drop the streamed text so far.
      textBuffer = "";
      thinkingBuffer = "";
      for (let index = blocks.length - 1; index >= 0; index -= 1) {
        if (blocks[index].kind === "text" || blocks[index].kind === "thinking") {
          blocks.splice(index, 1);
        }
      }
      continue;
    }
    const step = stepsBySequence.get(event.sequence);
    if (!step) continue;
    flushThinking();
    flushText();
    const last = blocks[blocks.length - 1];
    if (last?.kind === "steps") {
      last.steps.push(step);
    } else {
      blocks.push({ kind: "steps", key: `steps-${step.key}`, steps: [step] });
    }
  }
  flushThinking();
  flushText();
  return blocks;
}

export function summarizeRunSteps(steps: RunStep[]): RunStepSummary {
  // Subagent children count toward the totals — the work happened even
  // though it renders nested under the spawn card.
  const all = steps.flatMap((step) => [step, ...step.children]);
  return {
    total: all.length,
    queries: all.filter((step) => step.category === "sql").length,
    codeRuns: all.filter(
      (step) => step.category === "python" || step.category === "terminal",
    ).length,
    files: all.filter(
      (step) =>
        step.category === "file-write" ||
        step.category === "file-edit" ||
        step.category === "artifact",
    ).length,
    errors: all.filter((step) => step.status === "failed").length,
    running: all.some((step) => step.status === "running"),
  };
}

/** Compact tally for one subagent's child work, e.g. "12 reads · 2 queries". */
export function describeSubagentWork(step: RunStep): string {
  const counts = new Map<string, number>();
  const bump = (label: string) =>
    counts.set(label, (counts.get(label) ?? 0) + 1);
  for (const child of step.children) {
    if (child.category === "sql") bump("query");
    else if (child.category === "file-read") bump("read");
    else if (child.category === "file-write" || child.category === "file-edit")
      bump("edit");
    else if (child.category === "python" || child.category === "terminal")
      bump("run");
    else bump("tool call");
  }
  if (!counts.size) return "starting";
  return [...counts.entries()]
    .map(([label, count]) => `${count} ${label}${count === 1 ? "" : "s"}`)
    .join(" · ");
}

export function formatStepDuration(durationMs: number | null): string | null {
  if (durationMs == null) return null;
  if (durationMs < 100) return "<0.1s";
  if (durationMs < 60_000) return `${(durationMs / 1000).toFixed(1)}s`;
  const minutes = Math.floor(durationMs / 60_000);
  const seconds = Math.round((durationMs % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}
