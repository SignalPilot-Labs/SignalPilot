import { asRecord, text } from "./payload";
import type {
  ArtifactResult,
  ColumnProfileResult,
  DbtRunResult,
  KnowledgeResult,
  ProfiledColumn,
  SchemaColumn,
  SchemaResult,
  TableListEntry,
  TableListResult,
  TableResult,
  TerminalResult,
  ToolResultBase,
  ToolResultCell,
  ValidationResult,
} from "./tool-result-types";

/**
 * Per-kind parsers for the wire `ToolResult` objects. Every accessor
 * coerces: a missing or malformed field becomes its empty value, never a
 * throw. `tool-results.ts` dispatches on `kind` and adds the shared base.
 */

// --- coercion helpers -------------------------------------------------------

const num = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const int = (value: unknown, fallback = 0): number => num(value) ?? fallback;
const bool = (value: unknown, fallback = false): boolean =>
  typeof value === "boolean" ? value : fallback;
const nullableBool = (value: unknown): boolean | null =>
  typeof value === "boolean" ? value : null;
const str = (value: unknown): string =>
  typeof value === "string" ? value : "";
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const records = (value: unknown): Record<string, unknown>[] =>
  list(value)
    .map(asRecord)
    .filter((item): item is Record<string, unknown> => item !== null);
const strings = (value: unknown): string[] =>
  list(value).filter((item): item is string => typeof item === "string");
const cell = (value: unknown): ToolResultCell =>
  typeof value === "string" ||
  typeof value === "boolean" ||
  (typeof value === "number" && Number.isFinite(value))
    ? value
    : null;
const oneOf = <T extends string>(
  value: unknown,
  allowed: readonly T[],
  fallback: T,
): T => (allowed.includes(value as T) ? (value as T) : fallback);

// --- per-kind parsers ------------------------------------------------------

export function parseTable(r: Record<string, unknown>): Omit<TableResult, keyof ToolResultBase> {
  const rows = list(r.rows).map((row) => list(row).map(cell));
  return {
    kind: "table",
    columns: records(r.columns).map((column) => ({
      name: str(column.name),
      logicalType: text(column.logical_type),
    })),
    rows,
    previewRowCount: int(r.preview_row_count, rows.length),
    rowCount: num(r.row_count),
    queryRowCount: num(r.query_row_count),
    previewTruncated: bool(r.preview_truncated),
    columnsTruncated: bool(r.columns_truncated),
    resultId: text(r.result_id),
    executionId: text(r.execution_id),
    executionMs: num(r.execution_ms),
    completeness: oneOf(r.completeness, ["complete", "truncated", "unknown"], "unknown"),
    truncationReason: text(r.truncation_reason),
    piiRedactedColumns: strings(r.pii_redacted_columns),
    source: oneOf(r.source, ["structured", "parsed"], "parsed"),
  };
}

export function parseTableList(r: Record<string, unknown>): Omit<TableListResult, keyof ToolResultBase> {
  const entries: TableListEntry[] = records(r.entries).map((entry) => ({
    name: str(entry.name),
    rowCount: num(entry.row_count),
    rowCountLabel: text(entry.row_count_label),
    columns: records(entry.columns).map((column) => ({
      name: str(column.name),
      primaryKey: bool(column.primary_key),
      references: text(column.references),
    })),
    columnsTruncated: bool(entry.columns_truncated),
  }));
  return {
    kind: "table_list",
    connection: text(r.connection),
    database: text(r.database),
    dbType: text(r.db_type),
    total: int(r.total, entries.length),
    entries,
    entriesTruncated: bool(r.entries_truncated),
    databases: records(r.databases).map((db) => ({
      name: str(db.name),
      tableCount: int(db.table_count),
    })),
  };
}

export function parseSchema(r: Record<string, unknown>): Omit<SchemaResult, keyof ToolResultBase> {
  const columns: SchemaColumn[] = records(r.columns).map((column) => ({
    name: str(column.name),
    type: str(column.type),
    nullable: nullableBool(column.nullable),
    primaryKey: bool(column.primary_key),
    foreignKey: text(column.foreign_key),
    comment: text(column.comment),
    pii: text(column.pii),
  }));
  const sampleValues: Record<string, string[]> = {};
  for (const [name, values] of Object.entries(asRecord(r.sample_values) ?? {})) {
    sampleValues[name] = strings(values);
  }
  return {
    kind: "schema",
    table: str(r.table),
    description: text(r.description),
    owner: text(r.owner),
    rowCount: num(r.row_count),
    engine: text(r.engine),
    columns,
    columnsTruncated: bool(r.columns_truncated),
    foreignKeys: records(r.foreign_keys).map((fk) => ({
      column: str(fk.column),
      references: str(fk.references),
    })),
    referencedBy: records(r.referenced_by).map((ref) => ({
      table: str(ref.table),
      column: str(ref.column),
      referencesColumn: str(ref.references_column),
    })),
    sampleValues,
  };
}

export function parseColumnProfile(r: Record<string, unknown>): Omit<ColumnProfileResult, keyof ToolResultBase> {
  const columns: ProfiledColumn[] = records(r.columns).map((column) => ({
    name: str(column.name),
    type: text(column.type),
    primaryKey: bool(column.primary_key),
    nullable: nullableBool(column.nullable),
    comment: text(column.comment),
    distinctCount: num(column.distinct_count),
    uniqueness: num(column.uniqueness),
    min: text(column.min),
    max: text(column.max),
    avg: text(column.avg),
    nullCount: num(column.null_count),
    nullPct: num(column.null_pct),
    sampleValues: strings(column.sample_values),
    topValues: records(column.top_values).map((top) => ({
      value: str(top.value),
      count: int(top.count),
    })),
  }));
  return {
    kind: "column_profile",
    table: str(r.table),
    rowCount: num(r.row_count),
    filter: text(r.filter),
    columns,
    columnsTruncated: bool(r.columns_truncated),
  };
}

export function parseValidation(
  r: Record<string, unknown>,
  fallbackValid: boolean,
): Omit<ValidationResult, keyof ToolResultBase> {
  return {
    kind: "validation",
    valid: bool(r.valid, fallbackValid),
    estimatedRows: num(r.estimated_rows),
    expensive: bool(r.expensive),
    message: text(r.message),
    suggestedFix: text(r.suggested_fix),
    checks: strings(r.checks),
  };
}

export function parseDbtRun(r: Record<string, unknown>): Omit<DbtRunResult, keyof ToolResultBase> {
  const statuses: Record<string, number> = {};
  for (const [status, count] of Object.entries(asRecord(r.statuses) ?? {})) {
    const value = num(count);
    if (value !== null) statuses[status] = value;
  }
  const total = int(r.total, Object.values(statuses).reduce((a, b) => a + b, 0));
  return {
    kind: "dbt_run",
    command: text(r.command),
    targetSchema: text(r.target_schema),
    sync: text(r.sync),
    exitCode: num(r.exit_code),
    statuses,
    total,
    failures: records(r.failures).map((failure) => ({
      node: str(failure.node),
      message: str(failure.message),
    })),
    elapsedS: num(r.elapsed_s),
    log: str(r.log),
    logTruncated: bool(r.log_truncated),
  };
}

export function parseTerminal(r: Record<string, unknown>): Omit<TerminalResult, keyof ToolResultBase> {
  return {
    kind: "terminal",
    command: text(r.command),
    exitCode: num(r.exit_code),
    stdout: str(r.stdout),
    stderr: str(r.stderr),
    stdoutTruncated: bool(r.stdout_truncated),
    stderrTruncated: bool(r.stderr_truncated),
  };
}

export function parseKnowledge(r: Record<string, unknown>): Omit<KnowledgeResult, keyof ToolResultBase> {
  const docs = records(r.docs).map((doc) => ({
    id: text(doc.id),
    scope: text(doc.scope),
    category: text(doc.category),
    title: str(doc.title),
    snippet: text(doc.snippet),
  }));
  return {
    kind: "knowledge",
    mode: oneOf(r.mode, ["get", "search", "read"], "search"),
    query: text(r.query),
    docs,
    total: int(r.total, docs.length),
    docsTruncated: bool(r.truncated),
  };
}

export function parseArtifact(r: Record<string, unknown>): Omit<ArtifactResult, keyof ToolResultBase> {
  return {
    kind: "artifact",
    artifactKind: oneOf(r.artifact_kind, ["dashboard", "notebook"], "notebook"),
    published: bool(r.published),
    filename: text(r.filename),
    artifactIndex: num(r.artifact_index),
    status: text(r.status),
    nextRequiredAction: text(r.next_required_action),
    sessionId: text(r.session_id),
    notebookPath: text(r.notebook_path),
    notebook: text(r.notebook),
    dashboardSessionId: text(r.dashboard_session_id),
  };
}
