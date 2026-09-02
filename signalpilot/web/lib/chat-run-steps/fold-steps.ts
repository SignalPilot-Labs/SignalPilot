import type { StandaloneChatEvent } from "~/lib/api";
import {
  asRecord,
  chatToolSummary,
  CONNECTOR_NEEDS_SIGN_IN,
  durationBetween,
  text,
} from "./payload";
import {
  categorizeTool,
  extractCode,
  extractFile,
  extractSources,
  humanizeTool,
  normalizeToolName,
  SUBAGENT_SPAWN_TOOLS,
} from "./tool-names";
import { parseToolResult } from "./tool-results";
import type { RunStep } from "./types";

/**
 * Folds the raw standalone-chat run event stream into a compact list of
 * renderable "steps" for the agent activity timeline. Pure and synchronous so
 * it can be unit tested and replayed deterministically on the fixture page.
 */

/** Fresh per-step defaults for the subagent fields (never share the array). */
function emptyStepExtras(): Pick<
  RunStep,
  "result" | "children" | "subagentType" | "report" | "liveText"
> {
  return {
    result: null,
    children: [],
    subagentType: null,
    report: null,
    liveText: "",
  };
}

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
      // Structured output (table / schema / dbt run ...) for the tool card;
      // legacy events fold to `kind: "legacy"` with no summary.
      step.result = parseToolResult(event.payload, step.tool ?? "", failed);
      if (!failed && step.result.summary !== null) {
        step.detail = step.result.summary;
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
          // never repeats the agent-facing error text. The tool card's
          // error banner reads `result.errorMessage` and the generic chip
          // stat reads `result.summary`, so clear both too.
          step.title = `${step.title} · needs sign-in`;
          step.detail = null;
          if (step.result) step.result = { ...step.result, summary: null, errorMessage: null };
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
