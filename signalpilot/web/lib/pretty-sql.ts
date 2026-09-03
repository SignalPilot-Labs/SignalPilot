import { format as formatSql } from "sql-formatter";

/** Uppercased, indented SQL for display; returns the input on parse failure. */
export function prettySql(sql: string): string {
  try {
    return formatSql(sql, { language: "postgresql", keywordCase: "upper" });
  } catch {
    return sql;
  }
}
