---
sidebar_position: 3
---

# Schema & Exploration Tools

9 tools for exploring database schemas, table structures, and column distributions.

---

## list_tables

Compact one-line-per-table overview of all tables in a database.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `schema` | string | No | Filter to a specific schema |

**Returns:** Table name, schema, column count, PK count, FK count, row count.

**When to use:** First call in any exploration session. Orients you in the schema before drilling in.

---

## describe_table

Full column detail for a single table.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `table` | string | Yes | Table name (with schema if needed) |

**Returns:** Per-column: name, data type, nullability, PK/FK flag, any PII annotation.

---

## explore_table

Deep-dive into a table: column details + FK references + sample values + referenced tables.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `table` | string | Yes | Table name |
| `sample_rows` | integer | No | Number of sample rows to return (default: 5) |

**Returns:** Full column metadata, FK relationships, sample rows, tables that reference this table.

---

## explore_column

Distinct values with counts and NULL stats for a single column. Supports an optional LIKE filter.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `table` | string | Yes | Table name |
| `column` | string | Yes | Column name |
| `filter` | string | No | LIKE pattern to filter distinct values |
| `limit` | integer | No | Max distinct values to return (default: 50) |

**Returns:** Distinct values with row counts, percentages, NULL count, total distinct count.

**When to use:** Before filtering on a categorical column — understand what values exist.

---

## explore_columns

Multi-column statistics in a single call.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `table` | string | Yes | Table name |
| `columns` | array | Yes | List of column names to profile |

**Returns:** Per-column: distinct count, uniqueness ratio, min/max/avg (numeric), NULL count, sample values.

**When to use:** Data profiling — understand the shape of multiple columns at once.

---

## schema_overview

Database-wide summary: table count, total rows, FK density, hub tables.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |

**Returns:** Table count, total rows, FK density (FKs per table), most-connected tables.

---

## schema_ddl

Full schema as `CREATE TABLE` DDL statements with FK constraints.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `schema` | string | No | Filter to a specific schema |
| `table` | string | No | Filter to a single table |

**Returns:** DDL string. Useful for feeding schema context into prompts or comparing schemas.

---

## schema_statistics

High-level statistics: table sizes and FK connectivity, sorted by row count.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |

**Returns:** Per-table row count, size estimate, FK in/out count — sorted largest to smallest.

---

## schema_diff

Compare the current schema against the last cached version. Returns DDL-level changes.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |

**Returns:** Added tables, removed tables, modified tables (columns added/removed/changed), FK changes.

**When to use:** After a migration or dbt model promotion — verify only expected changes landed.
