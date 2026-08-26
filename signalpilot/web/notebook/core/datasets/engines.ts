import type { TypedString } from "@/utils/typed";

export type ConnectionName = TypedString<"ConnectionName">;

// DuckDB engine is treated as the default engine
// As it doesn't require passing an engine variable to the backend
export const DUCKDB_ENGINE = "__sp_duckdb" as ConnectionName;
export const INTERNAL_SQL_ENGINES = new Set([DUCKDB_ENGINE]);
export const DEFAULT_DUCKDB_DATABASE = "memory";
