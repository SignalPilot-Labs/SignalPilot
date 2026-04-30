"""Schema utility functions for SignalPilot Gateway.

Shared constants and helpers for schema compression, deduplication,
grouping, and join inference.  Extracted from main.py to eliminate
duplication (5 copies of TYPE_COMPRESSION_MAP, 4+ copies of string-type
sets) and make them independently testable.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

# ---------------------------------------------------------------------------
# Canonical type-compression map
# ---------------------------------------------------------------------------
# Merges all five inline ``type_map`` / ``_type_compress`` dicts that were
# scattered through main.py.  Every key is UPPER-CASE so callers should
# ``.upper()`` the raw column type before lookup.
TYPE_COMPRESSION_MAP: dict[str, str] = {
    "CHARACTER VARYING": "VARCHAR",
    "TIMESTAMP WITHOUT TIME ZONE": "TIMESTAMP",
    "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ",
    "DOUBLE PRECISION": "DOUBLE",
    "BOOLEAN": "BOOL",
    "INTEGER": "INT",
    "BIGINT": "BIGINT",
    "SMALLINT": "SMALLINT",
    "REAL": "FLOAT",
}

# ---------------------------------------------------------------------------
# Canonical string-column-type set
# ---------------------------------------------------------------------------
# Union of every ``_str_types`` / ``_string_types`` / ``string_types`` set
# found in main.py.  Stored as a frozenset so it is hashable and immutable.
# Includes both lower-case and mixed-case variants that appeared in the
# original copies so callers can do a direct ``col_type in STRING_COLUMN_TYPES``
# check without normalising case first.
STRING_COLUMN_TYPES: frozenset[str] = frozenset(
    {
        # lower-case variants
        "varchar",
        "nvarchar",
        "text",
        "char",
        "nchar",
        "character varying",
        "character",
        "enum",
        "string",
        # mixed/upper-case variants that appeared in original sets
        "String",
        "VARCHAR",
        "TEXT",
        "CHAR",
        "NVARCHAR",
    }
)


# ---------------------------------------------------------------------------
# Helper: compress a single SQL type string
# ---------------------------------------------------------------------------


def compress_type(raw_type: str) -> str:
    """Return a shorter alias for *raw_type* using :data:`TYPE_COMPRESSION_MAP`.

    The lookup is case-insensitive (input is upper-cased before matching).
    If no mapping exists the original string is returned unchanged.

    >>> compress_type("character varying")
    'VARCHAR'
    >>> compress_type("jsonb")
    'jsonb'
    """
    return TYPE_COMPRESSION_MAP.get(raw_type.upper(), raw_type)


# ---------------------------------------------------------------------------
# _compress_schema
# ---------------------------------------------------------------------------


def _compress_schema(
    schema: dict[str, Any],
    sample_values: dict[str, dict[str, list]] | None = None,
) -> dict[str, Any]:
    """Compress schema to DDL-style representation for LLM context efficiency.

    Top Spider2.0 performers use table compression for schemas >50K tokens.
    This reduces token count by ~60-70% while preserving:
    - Table and column names + types
    - Primary keys and foreign keys (critical for join path discovery)
    - Row counts (helps query planning)
    - Index information (helps optimization)
    - Sample values for ENUM-like columns (helps semantic understanding)
    """
    sample_values = sample_values or {}
    compressed: dict[str, Any] = {}

    for key, table in schema.items():
        cols: list[str] = []
        pk_cols: list[str] = []
        table_samples = sample_values.get(key, {})

        for col in table.get("columns", []):
            col_type = col.get("type", "")
            nullable = "" if col.get("nullable", True) else " NOT NULL"

            # Cardinality hints (helps Spider2.0 agent understand data distribution)
            unique_hint = ""
            stats = col.get("stats", {})
            is_enum_like = False
            if stats.get("distinct_fraction") == -1.0:
                unique_hint = " UNIQUE"
            elif col.get("low_cardinality"):
                unique_hint = " ENUM"
                is_enum_like = True
            elif (
                stats.get("distinct_count")
                and stats["distinct_count"] <= 10
                and col_type.lower()
                not in (
                    "timestamp",
                    "timestamptz",
                    "timestamp with time zone",
                    "timestamp without time zone",
                    "date",
                    "datetime",
                    "datetime2",
                )
            ):
                unique_hint = " ENUM"
                is_enum_like = True

            # Column comments help Spider2.0 agents understand column semantics
            comment = col.get("comment", "")
            comment_str = f" -- {comment}" if comment else ""

            # Inline sample values for ENUM-like columns (Spider2.0: helps agent
            # understand valid values without running a SELECT DISTINCT)
            col_name = col["name"]
            if is_enum_like and col_name in table_samples:
                vals = table_samples[col_name][:5]
                if vals:
                    val_str = ", ".join(repr(v) for v in vals)
                    comment_str = f" -- values: {val_str}" + (f" | {comment}" if comment else "")

            cols.append(f"{col_name} {col_type}{nullable}{unique_hint}{comment_str}")
            if col.get("primary_key"):
                pk_cols.append(col_name)

        # Build compact DDL string
        overview_kw = "CREATE VIEW" if table.get("type") == "view" else "CREATE TABLE"
        ddl_parts = [f"{overview_kw} {table.get('schema', '')}.{table['name']} ("]
        ddl_parts.append("  " + ", ".join(cols))
        if pk_cols:
            ddl_parts.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")
        ddl_parts.append(")")

        # Foreign keys as compact references
        fk_refs: list[str] = []
        for fk in table.get("foreign_keys", []):
            ref_table = fk.get("references_table", "")
            if fk.get("references_schema"):
                ref_table = f"{fk['references_schema']}.{ref_table}"
            fk_refs.append(f"{fk['column']} -> {ref_table}.{fk.get('references_column', '')}")

        compressed[key] = {
            "ddl": "\n".join(ddl_parts),
            "row_count": table.get("row_count", 0),
        }
        if table.get("size_mb"):
            compressed[key]["size_mb"] = table["size_mb"]
        if fk_refs:
            compressed[key]["foreign_keys"] = fk_refs
        if table.get("indexes"):
            compressed[key]["indexes"] = [idx.get("name", "") for idx in table["indexes"]]
        if table.get("description"):
            compressed[key]["description"] = table["description"]
        # ClickHouse-specific
        if table.get("engine"):
            compressed[key]["engine"] = table["engine"]
        if table.get("sorting_key"):
            compressed[key]["sorting_key"] = table["sorting_key"]
        # Redshift-specific
        if table.get("diststyle"):
            compressed[key]["diststyle"] = table["diststyle"]
        if table.get("sortkey"):
            compressed[key]["sortkey"] = table["sortkey"]
        # Snowflake-specific
        if table.get("clustering_key"):
            compressed[key]["clustering_key"] = table["clustering_key"]

    return compressed


# ---------------------------------------------------------------------------
# _deduplicate_partitioned_tables
# ---------------------------------------------------------------------------


def _deduplicate_partitioned_tables(
    schema: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """ReFoRCE-style deduplication of date/number-partitioned table families.

    Enterprise schemas often contain hundreds of identically-structured tables
    with date suffixes (e.g., ``ga_sessions_20160801`` through
    ``ga_sessions_20170801``).  ReFoRCE's ablation shows this is the single
    most impactful compression step (3-4% EX degradation if disabled).

    Returns:
        A ``(deduplicated_schema, partition_map)`` tuple where
        *partition_map* maps the representative table key to the list of
        all member keys.
    """
    # Pattern: table name ending with date-like suffix (YYYYMMDD, YYYY_MM_DD,
    # YYYY_MM, etc.) or numeric partition suffix (_001, _002, _p1, _p2, ...)
    date_suffixes = re.compile(
        r"^(.+?)_?"
        r"(?:"
        r"(\d{8})"  # YYYYMMDD
        r"|(\d{4}_\d{2}_\d{2})"  # YYYY_MM_DD
        r"|(\d{4}_\d{2})"  # YYYY_MM
        r"|(\d{4})"  # YYYY (only if 4+ tables match)
        r"|p(\d+)"  # p1, p2, ...
        r"|(\d{1,4})"  # numeric suffix (1, 2, ..., 001, 002)
        r")$"
    )

    # Group tables by their base name (without partition suffix)
    base_groups: dict[str, list[str]] = defaultdict(list)
    non_partitioned: dict[str, Any] = {}

    for key, table in schema.items():
        table_name = table.get("name", key.split(".")[-1]).lower()
        match = date_suffixes.match(table_name)
        if match:
            base_name = match.group(1).rstrip("_")
            schema_prefix = key.rsplit(".", 1)[0] + "." if "." in key else ""
            group_key = f"{schema_prefix}{base_name}"
            base_groups[group_key].append(key)
        else:
            non_partitioned[key] = table

    # Only deduplicate groups with 3+ tables (avoid false positives)
    deduplicated: dict[str, Any] = dict(non_partitioned)
    partition_map: dict[str, list[str]] = {}

    for group_key, members in base_groups.items():
        if len(members) >= 3:
            # Verify structural similarity: all members should have same
            # column names
            col_sets: list[frozenset[str]] = []
            for m in members:
                cols = frozenset(c["name"] for c in schema[m].get("columns", []))
                col_sets.append(cols)

            # Check if at least 80% share the same structure
            if col_sets:
                most_common = max(set(col_sets), key=col_sets.count)
                similar_count = col_sets.count(most_common)
                if similar_count / len(members) >= 0.8:
                    # Keep the first table as representative, aggregate
                    # row counts
                    representative = members[0]
                    total_rows = sum(schema[m].get("row_count", 0) or 0 for m in members)
                    rep_data = dict(schema[representative])
                    rep_data["row_count"] = total_rows
                    rep_data["_partition_count"] = len(members)
                    rep_data["_partition_base"] = group_key.split(".")[-1] if "." in group_key else group_key
                    deduplicated[representative] = rep_data
                    partition_map[representative] = members
                    continue

            # Not structurally similar -- keep all
            for m in members:
                deduplicated[m] = schema[m]
        else:
            # Too few to be a partition family
            for m in members:
                deduplicated[m] = schema[m]

    return deduplicated, partition_map


# ---------------------------------------------------------------------------
# _group_tables
# ---------------------------------------------------------------------------


def _group_tables(schema: dict[str, Any]) -> dict[str, list[str]]:
    """Group related tables by naming patterns and FK relationships.

    ReFoRCE (Spider2.0 SOTA) uses pattern-based table grouping to compress
    large schemas.  Tables are grouped when they share a common prefix
    (e.g., ``order_items``, ``order_history`` -> ``"order"`` group) or are
    connected by foreign keys.
    """
    # Phase 1: Group by naming prefix (common enterprise pattern)
    prefix_groups: dict[str, list[str]] = defaultdict(list)
    for key in schema:
        table_name = schema[key].get("name", key.split(".")[-1])
        # Extract prefix -- first word before underscore
        parts = table_name.lower().split("_")
        if len(parts) >= 2:
            prefix = parts[0]
            prefix_groups[prefix].append(key)
        else:
            prefix_groups[table_name].append(key)

    # Phase 2: Merge FK-connected tables into same groups
    fk_graph: dict[str, set[str]] = defaultdict(set)
    for key, table in schema.items():
        for fk in table.get("foreign_keys", []):
            ref_schema = fk.get("references_schema", "")
            ref_table = fk.get("references_table", "")
            ref_key = f"{ref_schema}.{ref_table}" if ref_schema else ref_table
            # Find the actual key that matches
            for k in schema:
                if k == ref_key or k.endswith(f".{ref_table}"):
                    fk_graph[key].add(k)
                    fk_graph[k].add(key)
                    break

    # Merge prefix groups that are FK-connected
    groups: dict[str, list[str]] = {}
    assigned: set[str] = set()
    for prefix, members in sorted(prefix_groups.items(), key=lambda x: -len(x[1])):
        if len(members) >= 2:
            group_key = prefix
            group_members = set(members)
            # Add FK-connected tables
            for m in list(group_members):
                group_members.update(fk_graph.get(m, set()))
            groups[group_key] = sorted(group_members - assigned)
            assigned.update(group_members)

    # Remaining ungrouped tables
    ungrouped = [k for k in schema if k not in assigned]
    if ungrouped:
        groups["_other"] = sorted(ungrouped)

    # Remove empty groups
    return {k: v for k, v in groups.items() if v}


# ---------------------------------------------------------------------------
# _infer_implicit_joins
# ---------------------------------------------------------------------------


def _infer_implicit_joins(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Detect implicit join relationships via column name pattern matching.

    For databases without FK declarations (common in data lakes, Databricks,
    etc.), this finds joinable columns by matching patterns like::

        orders.customer_id   -> customers.id
        order_items.product_id -> products.id
        payments.order_id    -> orders.order_id OR orders.id

    Returns a list of inferred FK-like relationships with confidence scores.
    Only returns high-confidence matches (exact name conventions).
    """
    # Build lookup: table_name (lowered) -> (full_key, table_data)
    table_lookup: dict[str, tuple[str, dict]] = {}
    # Also build: column_name -> list of (full_key, table_data) that have it
    pk_columns: dict[str, list[tuple[str, dict]]] = {}

    for _key, table in schema.items():
        tbl_name = table.get("name", "").lower()
        tbl_schema = table.get("schema", "")
        full_name = f"{tbl_schema}.{table.get('name', '')}" if tbl_schema else table.get("name", "")
        table_lookup[tbl_name] = (full_name, table)

        # Track PK/id columns for matching
        for col in table.get("columns", []):
            cn = col["name"].lower()
            if col.get("primary_key") or cn == "id":
                if cn not in pk_columns:
                    pk_columns[cn] = []
                pk_columns[cn].append((full_name, table))

    inferred: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()

    def _add_inferred(
        from_schema: str,
        from_table: str,
        from_col: str,
        ref_table_data: dict,
        ref_col: str,
        confidence: str = "high",
    ) -> bool:
        edge_key = (
            from_schema + "." + from_table,
            from_col,
            ref_table_data.get("schema", "") + "." + ref_table_data.get("name", ""),
            ref_col,
        )
        if edge_key not in seen:
            seen.add(edge_key)
            inferred.append(
                {
                    "from_schema": from_schema,
                    "from_table": from_table,
                    "from_column": from_col,
                    "to_schema": ref_table_data.get("schema", ""),
                    "to_table": ref_table_data.get("name", ""),
                    "to_column": ref_col,
                    "inferred": True,
                    "confidence": confidence,
                }
            )
            return True
        return False

    # Build column name -> set of tables that have this column (for
    # shared-name joins)
    # col_lower -> [(full_key, table, actual_col_name)]
    col_to_tables: dict[str, list[tuple[str, dict, str]]] = {}
    for key, table in schema.items():
        for col in table.get("columns", []):
            cn = col["name"].lower()
            if cn not in col_to_tables:
                col_to_tables[cn] = []
            col_to_tables[cn].append((key, table, col["name"]))

    for key, table in schema.items():
        tbl_schema = table.get("schema", "")
        tbl_name = table.get("name", "").lower()

        # Skip if table already has explicit FKs -- don't duplicate
        existing_fk_cols = {fk["column"].lower() for fk in table.get("foreign_keys", [])}

        for col in table.get("columns", []):
            cn = col["name"].lower()
            if cn in existing_fk_cols:
                continue

            # Pattern 1: column ends with _id -> look for table with
            # matching prefix  (e.g., customer_id -> customers.id)
            if cn.endswith("_id") and cn != "id":
                prefix = cn[:-3]  # "customer"
                # Try plural forms
                candidates = [prefix, prefix + "s", prefix + "es"]
                if prefix.endswith("y"):
                    candidates.append(prefix[:-1] + "ies")  # category -> categories
                elif prefix.endswith(("s", "x", "z")):
                    candidates.append(prefix + "es")  # address -> addresses

                for candidate in candidates:
                    if candidate in table_lookup and candidate != tbl_name:
                        ref_full, ref_table = table_lookup[candidate]
                        # Find the matching PK/id column in the target table
                        ref_col = None
                        for rc in ref_table.get("columns", []):
                            rcn = rc["name"].lower()
                            if rc.get("primary_key") and rcn in ("id", cn):
                                ref_col = rc["name"]
                                break
                            if rcn == "id":
                                ref_col = rc["name"]
                        if not ref_col:
                            # Try matching the exact column name
                            for rc in ref_table.get("columns", []):
                                if rc["name"].lower() == cn:
                                    ref_col = rc["name"]
                                    break
                        if ref_col:
                            _add_inferred(
                                tbl_schema,
                                table.get("name", ""),
                                col["name"],
                                ref_table,
                                ref_col,
                            )
                            break

            # Pattern 2: column ends with Id (camelCase)
            # e.g., customerId -> customers.id
            elif cn.endswith("id") and cn != "id" and len(cn) > 2 and cn[-3].islower():
                prefix = cn[:-2].lower()  # "customer"
                candidates = [prefix, prefix + "s", prefix + "es"]
                if prefix.endswith("y"):
                    candidates.append(prefix[:-1] + "ies")
                for candidate in candidates:
                    if candidate in table_lookup and candidate != tbl_name:
                        _, ref_table = table_lookup[candidate]
                        for rc in ref_table.get("columns", []):
                            rcn = rc["name"].lower()
                            if rc.get("primary_key") or rcn == "id":
                                _add_inferred(
                                    tbl_schema,
                                    table.get("name", ""),
                                    col["name"],
                                    ref_table,
                                    rc["name"],
                                )
                                break
                        break

            # Pattern 3: shared column name with _id/_key suffix -> join
            # bridge (e.g., both orders.product_id and
            # order_items.product_id -> joinable)
            elif cn.endswith(("_id", "_key", "_code")) and cn != "id":
                entries = col_to_tables.get(cn, [])
                if len(entries) > 1:
                    for (
                        other_key,
                        other_table,
                        other_col_name,
                    ) in entries:
                        if other_key == key:
                            continue
                        other_name = other_table.get("name", "").lower()
                        if other_name == tbl_name:
                            continue
                        # Only add if the other table has this as a PK or
                        # it looks like a dimension table
                        is_pk_in_other = any(
                            rc["name"].lower() == cn and rc.get("primary_key") for rc in other_table.get("columns", [])
                        )
                        if is_pk_in_other:
                            _add_inferred(
                                tbl_schema,
                                table.get("name", ""),
                                col["name"],
                                other_table,
                                other_col_name,
                            )

    return inferred
