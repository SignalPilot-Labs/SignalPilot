/** Schema explorer data model and formatting helpers. */

export interface ColumnStats {
  distinct_count?: number;
  distinct_fraction?: number;
  data_bytes?: number;
  compressed_bytes?: number;
}

export interface Column {
  name: string;
  type: string;
  nullable: boolean;
  primary_key?: boolean;
  comment?: string;
  stats?: ColumnStats;
  encoding?: string;
  dist_key?: boolean;
  sort_key_position?: number;
  low_cardinality?: boolean;
}

export interface ForeignKey {
  column: string;
  references_table: string;
  references_column: string;
  references_schema?: string;
}

export interface TableSchema {
  schema: string;
  name: string;
  database?: string;
  columns: Column[];
  foreign_keys?: ForeignKey[];
  row_count?: number;
  description?: string;
  engine?: string;
  sorting_key?: string;
  diststyle?: string;
  sortkey?: string;
  clustering_key?: string;
  size_mb?: number;
  total_bytes?: number;
}

export interface SchemaData {
  connection_name: string;
  db_type: string;
  table_count: number;
  total_tables?: number;
  tables: Record<string, TableSchema>;
}

export interface PIIConfig {
  enabled: boolean;
  rules: Record<string, string>;
}

export type ViewMode = "columns" | "ddl";

export const EMPTY_PII_CONFIG: PIIConfig = { enabled: false, rules: {} };

export function formatCount(value: number | undefined): string {
  if (value == null) return "--";
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString();
}

export function formatBytes(table: TableSchema): string {
  const bytes = table.total_bytes ?? (table.size_mb == null ? undefined : table.size_mb * 1_048_576);
  if (bytes == null) return "--";
  if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  if (bytes >= 1_024) return `${(bytes / 1_024).toFixed(1)} KB`;
  return `${bytes.toFixed(0)} B`;
}

export function formatCardinality(stats: ColumnStats | undefined): string {
  if (!stats) return "--";
  if (stats.distinct_count != null) return formatCount(stats.distinct_count);
  if (stats.distinct_fraction != null) return `${(stats.distinct_fraction * 100).toFixed(1)}%`;
  return "--";
}

export function typeFamily(type: string): string {
  const normalized = type.toLowerCase();
  if (/int|serial/.test(normalized)) return "integer";
  if (/numeric|decimal|real|double|float/.test(normalized)) return "number";
  if (/char|text|string/.test(normalized)) return "text";
  if (/date|time/.test(normalized)) return "time";
  if (/bool/.test(normalized)) return "boolean";
  if (/json|variant|struct|array|map/.test(normalized)) return "structured";
  return "other";
}

export function findRule(rules: Record<string, string>, column: string): [string, string] | null {
  const normalized = column.toLowerCase();
  for (const [key, rule] of Object.entries(rules)) {
    if (key.toLowerCase() === normalized) return [key, rule];
  }
  return null;
}

export function tableIdentity(key: string, table: TableSchema): string {
  return table.schema ? `${table.schema}.${table.name}` : key;
}
