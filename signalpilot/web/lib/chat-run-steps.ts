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
  | "dbt"
  | "plan"
  | "approval"
  | "progress"
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
};

export type RunStepSummary = {
  total: number;
  queries: number;
  codeRuns: number;
  files: number;
  errors: number;
  running: boolean;
};

const SQL_TOOLS = new Set([
  "query_database",
  "explain_query",
  "validate_sql",
  "plan_query",
  "preview_query",
]);
const PYTHON_TOOLS = new Set(["run_scratch_python", "run_cells"]);
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
    run_scratch_python: "Ran Python calculation",
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
  if (tool === "run_scratch_python") return text(input.source);
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
   * when no tool_call_id is present). */
  const open: RunStep[] = [];
  /** Open steps keyed by tool_call_id — the reliable pairing when present. */
  const openById = new Map<string, RunStep>();
  const runEvents = events
    .filter((event) => event.run_id === runId)
    .sort((a, b) => a.sequence - b.sequence);

  for (const event of runEvents) {
    const key = `${event.run_id}-${event.sequence}`;
    if (event.type === "tool_started") {
      const rawTool = text(event.payload.tool) ?? "analysis tool";
      const { tool, origin } = normalizeToolName(rawTool);
      const category = categorizeTool(tool);
      const toolCallId = text(event.payload.tool_call_id);
      const input = asRecord(event.payload.input);
      const step: RunStep = {
        key,
        sequence: event.sequence,
        category,
        status: "running",
        title: humanizeTool(tool),
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
      };
      steps.push(step);
      open.push(step);
      if (toolCallId) openById.set(toolCallId, step);
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
      if (failed) {
        // The worker writes the failure text as `summary`; `message` is the
        // legacy field kept as a fallback.
        step.detail =
          text(event.payload.summary) ??
          text(event.payload.message) ??
          "The tool returned an error.";
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
        input: asRecord(event.payload),
        sql: text(event.payload.sql),
        code: null,
        file: null,
        sources: [],
        detail: text(event.payload.purpose),
        startedAt: event.created_at,
        endedAt: event.created_at,
        durationMs: null,
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
        input: asRecord(event.payload),
        sql: null,
        code: null,
        file: null,
        sources: [],
        detail:
          text(event.payload.route_reason) ?? text(event.payload.summary),
        startedAt: event.created_at,
        endedAt: event.created_at,
        durationMs: null,
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
        detail: text(event.payload.message) ?? "The run hit an error.",
        startedAt: event.created_at,
        endedAt: event.created_at,
        durationMs: null,
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

export type RunBlock =
  | { kind: "text"; key: string; text: string }
  | { kind: "steps"; key: string; steps: RunStep[] };

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
  const flushText = () => {
    if (!textBuffer.trim()) {
      textBuffer = "";
      return;
    }
    blocks.push({ kind: "text", key: `text-${textKey}`, text: textBuffer });
    textBuffer = "";
  };
  for (const event of runEvents) {
    if (event.type === "text_delta") {
      const delta = event.payload.delta;
      if (typeof delta === "string") {
        if (!textBuffer) textKey = `${event.run_id}-${event.sequence}`;
        textBuffer += delta;
      }
      continue;
    }
    if (
      event.type === "status" &&
      event.payload.reset_text === true
    ) {
      // A retry restarted the answer: drop the streamed text so far.
      textBuffer = "";
      for (let index = blocks.length - 1; index >= 0; index -= 1) {
        if (blocks[index].kind === "text") blocks.splice(index, 1);
      }
      continue;
    }
    const step = stepsBySequence.get(event.sequence);
    if (!step) continue;
    flushText();
    const last = blocks[blocks.length - 1];
    if (last?.kind === "steps") {
      last.steps.push(step);
    } else {
      blocks.push({ kind: "steps", key: `steps-${step.key}`, steps: [step] });
    }
  }
  flushText();
  return blocks;
}

export function summarizeRunSteps(steps: RunStep[]): RunStepSummary {
  return {
    total: steps.length,
    queries: steps.filter((step) => step.category === "sql").length,
    codeRuns: steps.filter(
      (step) => step.category === "python" || step.category === "terminal",
    ).length,
    files: steps.filter(
      (step) =>
        step.category === "file-write" ||
        step.category === "file-edit" ||
        step.category === "artifact",
    ).length,
    errors: steps.filter((step) => step.status === "failed").length,
    running: steps.some((step) => step.status === "running"),
  };
}

export function formatStepDuration(durationMs: number | null): string | null {
  if (durationMs == null) return null;
  if (durationMs < 100) return "<0.1s";
  if (durationMs < 60_000) return `${(durationMs / 1000).toFixed(1)}s`;
  const minutes = Math.floor(durationMs / 60_000);
  const seconds = Math.round((durationMs % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}
