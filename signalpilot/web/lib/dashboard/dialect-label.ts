const DIALECT_LABELS: Record<string, string> = {
  postgres: "PostgreSQL",
  duckdb: "DuckDB",
  mysql: "MySQL",
  snowflake: "Snowflake",
  bigquery: "BigQuery",
  redshift: "Redshift",
  clickhouse: "ClickHouse",
  databricks: "Databricks",
  mssql: "SQL Server",
  trino: "Trino",
  sqlite: "SQLite",
  xata: "Xata",
};

export function dashboardDialectLabel(connectionType?: string | null) {
  if (!connectionType) return "SQL";
  return DIALECT_LABELS[connectionType.toLowerCase()] ?? "SQL";
}
