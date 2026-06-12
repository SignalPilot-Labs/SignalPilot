---
sidebar_position: 3
---

# Schema & Exploration Tools

13 tools for exploring database schemas, table structures, column distributions, and relationships — 10 schema/exploration tools plus 3 relationship tools.

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

---

## get_date_boundaries

Return MIN/MAX dates across all DATE and TIMESTAMP columns in a table or database.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `table` | string | No | Specific table (omit for database-wide scan) |

**Returns:** Per-column MIN/MAX date boundaries.

**When to use:** Before writing date-range queries — anchor to actual data dates, not `current_date`.

---

## Relationships

### get_relationships

Return the full ERD for a database: all FK relationships as arrows or adjacency list.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `format` | string | No | `arrows` or `adjacency` (default: `arrows`) |

**Returns:** All FK relationships in the specified format.

---

### find_join_path

Discover FK-based join paths between two tables. Searches up to 6 hops.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `from_table` | string | Yes | Source table |
| `to_table` | string | Yes | Target table |
| `max_hops` | integer | No | Maximum join hops (default: 6) |

**Returns:** List of join paths with intermediate tables and join conditions.

---

### schema_link

Find tables relevant to a natural-language question. Maps NL → schema.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `question` | string | Yes | Natural-language question |
| `top_k` | integer | No | Number of tables to return (default: 5) |

**Returns:** Ranked list of relevant tables with relevance scores.
