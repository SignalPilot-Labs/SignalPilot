import { asRecord, chatToolSummary, text } from "./payload";
import {
  parseArtifact,
  parseColumnProfile,
  parseDbtRun,
  parseKnowledge,
  parseSchema,
  parseTable,
  parseTableList,
  parseTerminal,
  parseValidation,
} from "./tool-result-parsers";
import { normalizeToolName } from "./tool-names";
import type {
  JsonResult,
  LegacyResult,
  TextResult,
  ToolResult,
  ToolResultBase,
  ToolResultKind,
} from "./tool-result-types";

export type * from "./tool-result-types";

/**
 * Converts the wire `tool_completed.payload` into the client `ToolResult`.
 * Defensive by design: every field is coerced, malformed shapes degrade to
 * empty values, and nothing here ever throws — a bad payload must never take
 * the transcript down.
 */

const PLACEHOLDER_SUMMARIES = new Set([
  "the tool completed.",
  "the tool returned an error.",
]);

const num = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

// --- tool-name fallback ----------------------------------------------------

const KIND_BY_TOOL: Record<string, ToolResultKind> = {
  query_database: "table", preview_query: "table",
  list_tables: "table_list", list_databases: "table_list", search_tables: "table_list",
  describe_table: "schema", explore_table: "schema", get_table_schema: "schema",
  explore_columns: "column_profile", explore_column: "column_profile", profile_column: "column_profile",
  validate_sql: "validation", check_model_schema: "validation", validate_model_output: "validation",
  analyze_grain: "validation", verify_model_values: "validation", explain_query: "validation",
  dbt_execute: "dbt_run", refresh_mart: "dbt_run",
  sandbox_exec: "terminal", Bash: "terminal",
  get_knowledge: "knowledge", search_knowledge: "knowledge", read_knowledge: "knowledge",
  publish_table: "artifact", publish_chart: "artifact", publish_report: "artifact",
  create_dashboard_preview: "artifact", start_analysis_notebook: "artifact",
  inspect_dbt: "json", run_cells: "json", edit_notebook: "json",
  get_lightweight_cell_map: "json", get_notebook_errors: "json",
};

/** The result kind a tool is expected to produce, for cards on legacy events. */
export function toolResultKindForTool(normalizedTool: string): ToolResultKind | null {
  return KIND_BY_TOOL[normalizedTool] ?? null;
}

// --- entry point -----------------------------------------------------------

export function parseToolResult(
  payload: Record<string, unknown>,
  tool: string,
  isError: boolean,
): ToolResult {
  try {
    return parseUnsafe(payload, tool, isError);
  } catch {
    return { ...baseOf(payload, isError), kind: "legacy" };
  }
}

function baseOf(payload: Record<string, unknown>, isError: boolean): ToolResultBase {
  const summaryRaw = chatToolSummary(payload.summary);
  const summary =
    summaryRaw && !PLACEHOLDER_SUMMARIES.has(summaryRaw.trim().toLowerCase())
      ? summaryRaw
      : null;
  return {
    summary,
    resultText: text(payload.result_text),
    resultChars: num(payload.result_chars),
    truncated: payload.truncated === true,
    errorMessage: isError
      ? (chatToolSummary(payload.error_message) ??
        summary ??
        chatToolSummary(payload.message))
      : null,
  };
}

function parseUnsafe(
  payload: Record<string, unknown>,
  tool: string,
  isError: boolean,
): ToolResult {
  const base = baseOf(payload, isError);
  const normalizedTool = tool.startsWith("mcp__") ? normalizeToolName(tool).tool : tool;
  const result = asRecord(payload.result);
  if (!result) {
    if (normalizedTool === "validate_sql") {
      // Legacy validate_sql completion: the outcome is the error flag.
      return { ...base, ...parseValidation({}, !isError), message: base.summary };
    }
    if (base.resultText !== null) return { ...base, kind: "text" } satisfies TextResult;
    return { ...base, kind: "legacy" } satisfies LegacyResult;
  }
  switch (text(result.kind)) {
    case "table": return { ...base, ...parseTable(result) };
    case "table_list": return { ...base, ...parseTableList(result) };
    case "schema": return { ...base, ...parseSchema(result) };
    case "column_profile": return { ...base, ...parseColumnProfile(result) };
    case "validation": return { ...base, ...parseValidation(result, !isError) };
    case "dbt_run": return { ...base, ...parseDbtRun(result) };
    case "terminal": return { ...base, ...parseTerminal(result) };
    case "knowledge": return { ...base, ...parseKnowledge(result) };
    case "artifact": return { ...base, ...parseArtifact(result) };
    case "json": return { ...base, kind: "json", value: result.value } satisfies JsonResult;
    case "text": return { ...base, kind: "text" };
    default:
      // Unknown projector kind (newer backend): keep the raw object visible.
      return { ...base, kind: "json", value: result };
  }
}
