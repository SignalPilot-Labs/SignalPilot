/**
 * Grouping helpers for multi-database connections.
 *
 * One connection can expose several databases: MSSQL multi-db mode keys tables
 * as database.schema.table and stamps a `database` field on each table; Trino
 * and Databricks use catalog.schema.table with the catalog folded into the
 * `schema` string. Single-database connectors carry a plain schema name and no
 * database field — those group under the connection's configured database.
 */

export interface DatabaseGroupableTable {
  schema?: string;
  name: string;
  database?: string;
  row_count?: number;
  columns?: unknown[];
}

export interface DatabaseGroup {
  name: string;
  tableCount: number;
  schemaCount: number;
  columnCount: number;
  rowCount: number;
}

/** Database a table belongs to, or null when the connector is single-database. */
export function tableDatabase(table: DatabaseGroupableTable): string | null {
  if (table.database) return table.database;
  const schema = table.schema ?? "";
  const dot = schema.indexOf(".");
  return dot > 0 ? schema.slice(0, dot) : null;
}

/** Schema name with the database/catalog prefix stripped, for display inside one database. */
export function localSchema(table: DatabaseGroupableTable): string {
  const schema = table.schema || "default";
  const db = tableDatabase(table);
  if (db && schema.startsWith(`${db}.`)) return schema.slice(db.length + 1) || "default";
  return schema;
}

/** Group key for a table: its own database, or the connection-level fallback label. */
export function tableDatabaseKey(table: DatabaseGroupableTable, fallback: string): string {
  return tableDatabase(table) ?? fallback;
}

export function groupTablesByDatabase(
  tables: Record<string, DatabaseGroupableTable>,
  fallback: string,
): DatabaseGroup[] {
  const groups = new Map<string, { tables: number; schemas: Set<string>; columns: number; rows: number }>();
  for (const table of Object.values(tables)) {
    const name = tableDatabaseKey(table, fallback);
    let group = groups.get(name);
    if (!group) {
      group = { tables: 0, schemas: new Set(), columns: 0, rows: 0 };
      groups.set(name, group);
    }
    group.tables += 1;
    group.schemas.add(localSchema(table));
    group.columns += table.columns?.length ?? 0;
    group.rows += table.row_count ?? 0;
  }
  return [...groups.entries()]
    .map(([name, group]) => ({
      name,
      tableCount: group.tables,
      schemaCount: group.schemas.size,
      columnCount: group.columns,
      rowCount: group.rows,
    }))
    .sort((left, right) => left.name.localeCompare(right.name));
}

/** Human label for the implicit database of a single-database connection. */
export function connectionDefaultDatabase(connection?: {
  database?: string | null;
  catalog?: string | null;
  project?: string | null;
} | null): string {
  return connection?.database || connection?.catalog || connection?.project || "default";
}
