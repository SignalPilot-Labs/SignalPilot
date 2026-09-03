/**
 * Client-side (camelCase) view of the tool result carried on
 * `tool_completed.payload`. Mirrors the wire `ToolResult` union in
 * `lib/api/standalone-chat.ts`; `parseToolResult` in `tool-results.ts` is the
 * only place that converts between the two. Import-cycle free on purpose:
 * `types.ts` embeds `ToolResult` on `RunStep`.
 */

export type ToolResultCell = string | number | boolean | null;

/** Wire kinds the backend projector can emit. */
export type ToolResultKind =
  | "table"
  | "table_list"
  | "schema"
  | "column_profile"
  | "validation"
  | "dbt_run"
  | "terminal"
  | "knowledge"
  | "artifact"
  | "json"
  | "text";

export type ToolResultBase = {
  /** The worker's one-liner, or null when only the legacy placeholder came. */
  summary: string | null;
  /** Capped raw tool output, when the worker attached it. */
  resultText: string | null;
  /** Full output length before the cap. */
  resultChars: number | null;
  truncated: boolean;
  /** Sanitized error headline; null on success. */
  errorMessage: string | null;
};

export type TableColumn = { name: string; logicalType: string | null };

export type TableResult = ToolResultBase & {
  kind: "table";
  columns: TableColumn[];
  rows: ToolResultCell[][];
  previewRowCount: number;
  rowCount: number | null;
  queryRowCount: number | null;
  previewTruncated: boolean;
  columnsTruncated: boolean;
  resultId: string | null;
  executionId: string | null;
  executionMs: number | null;
  completeness: "complete" | "truncated" | "unknown";
  truncationReason: string | null;
  piiRedactedColumns: string[];
  source: "structured" | "parsed";
};

export type TableListEntry = {
  name: string;
  rowCount: number | null;
  rowCountLabel: string | null;
  columns: { name: string; primaryKey: boolean; references: string | null }[];
  columnsTruncated: boolean;
};

export type TableListResult = ToolResultBase & {
  kind: "table_list";
  connection: string | null;
  database: string | null;
  dbType: string | null;
  total: number;
  entries: TableListEntry[];
  entriesTruncated: boolean;
  databases: { name: string; tableCount: number }[];
};

export type SchemaColumn = {
  name: string;
  type: string;
  nullable: boolean | null;
  primaryKey: boolean;
  foreignKey: string | null;
  comment: string | null;
  pii: string | null;
};

export type SchemaResult = ToolResultBase & {
  kind: "schema";
  table: string;
  description: string | null;
  owner: string | null;
  rowCount: number | null;
  engine: string | null;
  columns: SchemaColumn[];
  columnsTruncated: boolean;
  foreignKeys: { column: string; references: string }[];
  referencedBy: { table: string; column: string; referencesColumn: string }[];
  sampleValues: Record<string, string[]>;
};

export type ProfiledColumn = {
  name: string;
  type: string | null;
  primaryKey: boolean;
  nullable: boolean | null;
  comment: string | null;
  distinctCount: number | null;
  uniqueness: number | null;
  min: string | null;
  max: string | null;
  avg: string | null;
  nullCount: number | null;
  nullPct: number | null;
  sampleValues: string[];
  topValues: { value: string; count: number }[];
};

export type ColumnProfileResult = ToolResultBase & {
  kind: "column_profile";
  table: string;
  rowCount: number | null;
  filter: string | null;
  columns: ProfiledColumn[];
  columnsTruncated: boolean;
};

export type ValidationResult = ToolResultBase & {
  kind: "validation";
  valid: boolean;
  estimatedRows: number | null;
  expensive: boolean;
  message: string | null;
  suggestedFix: string | null;
  checks: string[];
};

export type DbtRunResult = ToolResultBase & {
  kind: "dbt_run";
  command: string | null;
  targetSchema: string | null;
  sync: string | null;
  exitCode: number | null;
  statuses: Record<string, number>;
  total: number;
  failures: { node: string; message: string }[];
  elapsedS: number | null;
  log: string;
  logTruncated: boolean;
};

export type TerminalResult = ToolResultBase & {
  kind: "terminal";
  command: string | null;
  exitCode: number | null;
  stdout: string;
  stderr: string;
  stdoutTruncated: boolean;
  stderrTruncated: boolean;
};

export type KnowledgeDoc = {
  id: string | null;
  scope: string | null;
  category: string | null;
  title: string;
  snippet: string | null;
};

export type KnowledgeResult = ToolResultBase & {
  kind: "knowledge";
  mode: "get" | "search" | "read";
  query: string | null;
  docs: KnowledgeDoc[];
  total: number;
  /** The doc list was capped (distinct from the base `truncated` flag). */
  docsTruncated: boolean;
};

export type ArtifactResult = ToolResultBase & {
  kind: "artifact";
  artifactKind: "dashboard" | "notebook";
  published: boolean;
  filename: string | null;
  artifactIndex: number | null;
  status: string | null;
  nextRequiredAction: string | null;
  sessionId: string | null;
  notebookPath: string | null;
  notebook: string | null;
  dashboardSessionId: string | null;
};

export type JsonResult = ToolResultBase & { kind: "json"; value: unknown };

export type TextResult = ToolResultBase & { kind: "text" };

/** A pre-projector `tool_completed` (no `result`, placeholder summary). */
export type LegacyResult = ToolResultBase & { kind: "legacy" };

export type ToolResult =
  | TableResult
  | TableListResult
  | SchemaResult
  | ColumnProfileResult
  | ValidationResult
  | DbtRunResult
  | TerminalResult
  | KnowledgeResult
  | ArtifactResult
  | JsonResult
  | TextResult
  | LegacyResult;
