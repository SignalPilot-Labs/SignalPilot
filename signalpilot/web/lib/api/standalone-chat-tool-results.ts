// ---------------------------------------------------------------------------
// Tool results carried on `tool_completed.payload` (wire contract, snake_case).
// No new event type: old rows stay valid because `payload` is untyped, and
// every field below beyond `tool_call_id`/`error`/`summary` is optional.

export type ToolResultCell = string | number | boolean | null;

export type ToolResult =
  | {
      kind: "table";
      columns: { name: string; logical_type?: string | null }[];
      rows: ToolResultCell[][];
      preview_row_count: number;
      row_count: number | null;
      query_row_count?: number | null;
      preview_truncated: boolean;
      columns_truncated: boolean;
      result_id: string | null;
      execution_id?: string | null;
      execution_ms?: number | null;
      completeness: "complete" | "truncated" | "unknown";
      truncation_reason?: string | null;
      pii_redacted_columns?: string[];
      source: "structured" | "parsed";
    }
  | {
      kind: "table_list";
      connection?: string;
      database?: string;
      db_type?: string;
      total: number;
      entries: {
        name: string;
        row_count: number | null;
        row_count_label?: string;
        columns: { name: string; primary_key: boolean; references?: string }[];
        columns_truncated: boolean;
      }[];
      entries_truncated: boolean;
      databases?: { name: string; table_count: number }[];
    }
  | {
      kind: "schema";
      table: string;
      description?: string;
      owner?: string;
      row_count?: number | null;
      engine?: string;
      columns: {
        name: string;
        type: string;
        nullable: boolean | null;
        primary_key: boolean;
        foreign_key?: string;
        comment?: string;
        pii?: string;
      }[];
      columns_truncated: boolean;
      foreign_keys?: { column: string; references: string }[];
      referenced_by?: { table: string; column: string; references_column: string }[];
      sample_values?: Record<string, string[]>;
    }
  | {
      kind: "column_profile";
      table: string;
      row_count?: number | null;
      filter?: string;
      columns: {
        name: string;
        type?: string;
        primary_key?: boolean;
        nullable?: boolean | null;
        comment?: string;
        distinct_count?: number | null;
        uniqueness?: number | null;
        min?: string;
        max?: string;
        avg?: string;
        null_count?: number | null;
        null_pct?: number | null;
        sample_values?: string[];
        top_values?: { value: string; count: number }[];
      }[];
      columns_truncated: boolean;
    }
  | {
      kind: "validation";
      valid: boolean;
      estimated_rows?: number | null;
      expensive?: boolean;
      message?: string;
      suggested_fix?: string;
      checks?: string[];
    }
  | {
      kind: "dbt_run";
      command?: string;
      target_schema?: string;
      sync?: string;
      exit_code: number | null;
      statuses: Record<string, number>;
      total: number;
      failures: { node: string; message: string }[];
      elapsed_s?: number | null;
      log: string;
      log_truncated: boolean;
    }
  | {
      kind: "terminal";
      command?: string;
      exit_code: number | null;
      stdout: string;
      stderr: string;
      stdout_truncated: boolean;
      stderr_truncated: boolean;
    }
  | {
      kind: "knowledge";
      mode: "get" | "search" | "read";
      query?: string;
      docs: {
        id?: string;
        scope?: string;
        category?: string;
        title: string;
        snippet?: string;
      }[];
      total: number;
      truncated: boolean;
    }
  | {
      kind: "artifact";
      artifact_kind: "table" | "chart" | "report" | "dashboard" | "notebook";
      published: boolean;
      filename?: string;
      artifact_index?: number;
      status?: string;
      next_required_action?: string;
      session_id?: string;
      notebook_path?: string;
      notebook?: string;
      dashboard_session_id?: string;
    }
  | { kind: "json"; value: unknown }
  | { kind: "text" };

export type ToolCompletedPayload = {
  tool_call_id: string | null;
  parent_tool_call_id?: string;
  error: boolean;
  /** Real one-liner ("1,204 rows · 312 ms") or the sanitized error headline. */
  summary: string;
  /** Agent tool only: the subagent's final report. */
  report?: string;
  /** Echo of the tool name. */
  tool?: string;
  /** Always present on new events (at minimum `{kind: "text"}`). */
  result?: ToolResult;
  /** Capped raw tool output (≤ 8192 chars). */
  result_text?: string;
  /** Full output length before the cap. */
  result_chars?: number;
  truncated?: boolean;
  v?: 1;
};
