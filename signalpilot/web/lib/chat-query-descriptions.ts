import type { SqlTraceExecution, StandaloneChatEvent } from "~/lib/api";

/**
 * Join the conversation's governed query executions to the agent's
 * one-sentence `description` for each query_database call.
 *
 * The trace comes from the gateway's execution table, which never sees the
 * description (the tool discards it before running). The run events do carry
 * it in `tool_started.input`, so the panel matches the two client-side: by
 * `execution_id` when the structured result reported one, otherwise by the
 * SQL text with whitespace collapsed. Each description is used once, in
 * order, so two identical queries with different descriptions still line up.
 */

const QUERY_TOOL_SUFFIX = "query_database";

type DescribedQuery = {
  description: string;
  sql: string | null;
  toolCallId: string | null;
};

export function normalizeSql(sql: string | null | undefined): string | null {
  if (typeof sql !== "string") return null;
  const collapsed = sql.replace(/\s+/g, " ").trim().replace(/;\s*$/, "").trim();
  return collapsed ? collapsed.toLowerCase() : null;
}

function readDescription(input: unknown): string | null {
  if (!input || typeof input !== "object") return null;
  const value = (input as Record<string, unknown>).description;
  if (typeof value !== "string") return null;
  const sentence = value.replace(/\s+/g, " ").trim().replace(/[.\s]+$/, "");
  return sentence || null;
}

function readSql(input: unknown): string | null {
  if (!input || typeof input !== "object") return null;
  const record = input as Record<string, unknown>;
  const sql = record.sql ?? record.query;
  return typeof sql === "string" ? sql : null;
}

function isQueryTool(tool: unknown): boolean {
  return typeof tool === "string" && tool.split("__").pop() === QUERY_TOOL_SUFFIX;
}

/** Description keyed by execution_id. Executions without a match are absent. */
export function describeQueryExecutions(
  events: StandaloneChatEvent[],
  executions: SqlTraceExecution[],
): Map<string, string> {
  const queries: DescribedQuery[] = [];
  const executionIdByCall = new Map<string, string>();
  for (const event of events) {
    if (event.type === "tool_started" && isQueryTool(event.payload.tool)) {
      const description = readDescription(event.payload.input);
      if (!description) continue;
      const toolCallId =
        typeof event.payload.tool_call_id === "string" ? event.payload.tool_call_id : null;
      queries.push({ description, sql: readSql(event.payload.input), toolCallId });
    } else if (event.type === "tool_completed") {
      const result = event.payload.result;
      const executionId =
        result && typeof result === "object"
          ? (result as Record<string, unknown>).execution_id
          : null;
      const toolCallId = event.payload.tool_call_id;
      if (typeof executionId === "string" && typeof toolCallId === "string") {
        executionIdByCall.set(toolCallId, executionId);
      }
    }
  }
  const out = new Map<string, string>();
  const used = new Set<DescribedQuery>();
  // Exact matches first so a repeated SQL text cannot steal a precise one.
  for (const query of queries) {
    const executionId = query.toolCallId ? executionIdByCall.get(query.toolCallId) : undefined;
    if (executionId && executions.some((e) => e.execution_id === executionId) && !out.has(executionId)) {
      out.set(executionId, query.description);
      used.add(query);
    }
  }
  for (const execution of executions) {
    if (out.has(execution.execution_id)) continue;
    const target = normalizeSql(execution.sql);
    if (!target) continue;
    const match = queries.find((q) => !used.has(q) && normalizeSql(q.sql) === target);
    if (!match) continue;
    out.set(execution.execution_id, match.description);
    used.add(match);
  }
  return out;
}
