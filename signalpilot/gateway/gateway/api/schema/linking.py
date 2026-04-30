"""Schema linking endpoint — find tables/columns relevant to a natural language question."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Query

from gateway.api.deps import (
    StoreD,
    get_filtered_schema,
    require_connection,
)
from gateway.api.schema._constants import _re_link
from gateway.api.schema._router import router
from gateway.api.schema._scoring import _build_join_hints
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache
from gateway.schema_utils import TYPE_COMPRESSION_MAP, compress_type
from gateway.scope_guard import RequireScope

logger = logging.getLogger(__name__)

# ── Dialect hints (Spider2.0 multi-database optimization) ─────────────────
# Tells the agent which SQL dialect to use and common pitfalls.
_DIALECT_HINTS: dict[str, dict[str, Any]] = {
    "postgres": {
        "dialect": "PostgreSQL",
        "identifier_quote": '"',
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "NOW(), CURRENT_DATE, DATE_TRUNC('month', col), EXTRACT(YEAR FROM col)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LENGTH(), SUBSTRING()",
        "tips": ["Use :: for type casting (e.g., col::TEXT)", "ILIKE for case-insensitive LIKE"],
    },
    "mysql": {
        "dialect": "MySQL",
        "identifier_quote": "`",
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "NOW(), CURDATE(), DATE_FORMAT(col, '%Y-%m'), YEAR(col), MONTH(col)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LENGTH(), SUBSTRING()",
        "tips": ["Use backticks for reserved words", "GROUP BY is strict — list all non-aggregated columns"],
    },
    "mssql": {
        "dialect": "T-SQL (SQL Server)",
        "identifier_quote": "[]",
        "string_quote": "'",
        "limit_syntax": "TOP n or OFFSET m ROWS FETCH NEXT n ROWS ONLY",
        "date_functions": "GETDATE(), CAST(col AS DATE), DATEPART(YEAR, col), DATEDIFF(DAY, a, b), FORMAT(col, 'yyyy-MM')",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LEN(), SUBSTRING()",
        "tips": ["Use TOP n instead of LIMIT", "Use OFFSET...FETCH for pagination", "Use [] for reserved words"],
    },
    "redshift": {
        "dialect": "Redshift (PostgreSQL-based)",
        "identifier_quote": '"',
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "GETDATE(), CURRENT_DATE, DATE_TRUNC('month', col), EXTRACT(YEAR FROM col), DATEDIFF(day, a, b)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LEN(), SUBSTRING()",
        "tips": ["PostgreSQL-like but no LATERAL joins", "Use APPROXIMATE COUNT(DISTINCT) for large tables"],
    },
    "snowflake": {
        "dialect": "Snowflake SQL",
        "identifier_quote": '"',
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "CURRENT_TIMESTAMP(), CURRENT_DATE(), DATE_TRUNC('month', col), EXTRACT(YEAR FROM col), DATEDIFF('day', a, b)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LENGTH(), SUBSTR()",
        "tips": [
            "Identifiers are case-insensitive unless double-quoted",
            "Use FLATTEN() for semi-structured data",
            "QUALIFY for window function filtering",
        ],
    },
    "bigquery": {
        "dialect": "BigQuery Standard SQL",
        "identifier_quote": "`",
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "CURRENT_TIMESTAMP(), CURRENT_DATE(), DATE_TRUNC(col, MONTH), EXTRACT(YEAR FROM col)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LENGTH(), SUBSTR()",
        "tips": [
            "Use backticks for project.dataset.table references",
            "Use UNNEST() for repeated fields",
            "QUALIFY for window filtering",
        ],
    },
    "clickhouse": {
        "dialect": "ClickHouse SQL",
        "identifier_quote": '"',
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "now(), today(), toStartOfMonth(col), toYear(col), dateDiff('day', a, b)",
        "string_functions": "concat(a, b), lower(), upper(), length(), substring()",
        "tips": [
            "Functions are case-sensitive and camelCase",
            "Use -If suffix for conditional aggregation (e.g., countIf, sumIf)",
            "Array functions: arrayJoin, groupArray",
        ],
    },
    "trino": {
        "dialect": "Trino SQL (ANSI-based)",
        "identifier_quote": '"',
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "CURRENT_TIMESTAMP, CURRENT_DATE, DATE_TRUNC('month', col), EXTRACT(YEAR FROM col)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LENGTH(), SUBSTR()",
        "tips": [
            "Use catalog.schema.table for cross-catalog queries",
            "UNNEST() for arrays",
            "Supports ANSI SQL window functions",
        ],
    },
    "databricks": {
        "dialect": "Databricks SQL (Spark SQL-based)",
        "identifier_quote": "`",
        "string_quote": "'",
        "limit_syntax": "LIMIT n",
        "date_functions": "CURRENT_TIMESTAMP(), CURRENT_DATE(), DATE_TRUNC('MONTH', col), EXTRACT(YEAR FROM col)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LENGTH(), SUBSTRING()",
        "tips": [
            "Use backticks for identifiers",
            "Supports QUALIFY for window filtering",
            "Use catalog.schema.table for Unity Catalog",
        ],
    },
    "duckdb": {
        "dialect": "DuckDB SQL (PostgreSQL-compatible)",
        "identifier_quote": '"',
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "NOW(), CURRENT_DATE, DATE_TRUNC('month', col), EXTRACT(YEAR FROM col), DATE_DIFF('day', a, b)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LENGTH(), SUBSTRING()",
        "tips": ["Very PostgreSQL-compatible", "Supports LIST and STRUCT types", "PIVOT/UNPIVOT supported natively"],
    },
}


@router.get("/connections/{name}/schema/link", dependencies=[RequireScope("read")])
async def schema_link(
    name: str,
    store: StoreD,
    question: str = Query(..., max_length=2000, description="Natural language question to link schema for"),
    format: str = Query(
        default="ddl",
        pattern="^(ddl|compact|json|condensed)$",
        description="Output format: ddl (full), condensed (pruned columns), compact (one-line), json",
    ),
    max_tables: int = Query(default=20, ge=1, le=100, description="Max tables in linked schema"),
    prune_columns: bool = Query(
        default=False, description="Drop columns with 0 relevance from low-scoring tables (reduces token count 30-60%%)"
    ),
):
    """Smart schema linking — find tables and columns relevant to a natural language question.

    Implements high-recall schema linking optimized for Spider2.0:
    1. Tokenizes the question into meaningful terms
    2. Matches terms against table names, column names, and comments
    3. Includes FK-connected tables for join path completeness
    4. Returns linked schema in DDL format (preferred by SOTA systems)

    Based on EDBT 2026 research: recall matters more than precision for schema linking.
    Better to include extra tables than miss a relevant one.
    """
    info = await require_connection(store, name)
    filtered = await get_filtered_schema(store, name, info)

    # ── Small-schema bypass (OpenReview "Death of Schema Linking?" finding) ──
    # When the full schema is small enough to fit the context window, skip scoring
    # and include all tables. SOTA systems achieve higher accuracy this way because
    # they can never miss a relevant table. Threshold: ≤ max_tables tables.
    total_columns = sum(len(t.get("columns", [])) for t in filtered.values())
    _small_schema = len(filtered) <= max_tables and total_columns <= 500

    # Step 1: Tokenize question into search terms
    # Extract meaningful words (3+ chars, not common SQL/English stopwords)
    stopwords = {
        "the",
        "and",
        "for",
        "are",
        "but",
        "not",
        "you",
        "all",
        "can",
        "had",
        "her",
        "was",
        "one",
        "our",
        "out",
        "has",
        "how",
        "man",
        "new",
        "now",
        "old",
        "see",
        "way",
        "who",
        "did",
        "get",
        "him",
        "his",
        "let",
        "say",
        "she",
        "too",
        "use",
        "what",
        "which",
        "show",
        "find",
        "list",
        "give",
        "tell",
        "many",
        "much",
        "each",
        "every",
        "from",
        "with",
        "that",
        "this",
        "have",
        "will",
        "your",
        "they",
        "been",
        "more",
        "when",
        "make",
        "like",
        "very",
        "just",
        "than",
        "them",
        "some",
        "would",
        "could",
        "select",
        "where",
        "group",
        "having",
        "limit",
        "result",
        "table",
        "column",
        "database",
        "query",
        "display",
        "retrieve",
    }
    # Semantic synonyms for common business/analytical terms that map to column names
    # This improves recall when the question uses different words than the schema
    _synonyms: dict[str, list[str]] = {
        "spending": ["amount", "total", "payment", "cost", "price", "revenue"],
        "revenue": ["amount", "total", "sales", "income", "price"],
        "bought": ["order", "purchase", "transaction"],
        "sold": ["order", "sale", "transaction"],
        "profit": ["margin", "revenue", "cost", "amount"],
        "expensive": ["price", "cost", "amount"],
        "cheapest": ["price", "cost", "amount"],
        "latest": ["date", "time", "created", "updated", "recent"],
        "oldest": ["date", "time", "created"],
        "biggest": ["count", "total", "amount", "size"],
        "active": ["status", "is_active", "enabled"],
        "inactive": ["status", "is_active", "enabled"],
        "location": ["city", "state", "country", "region", "address", "zip"],
        "address": ["city", "state", "country", "zip", "address_line"],
        "employee": ["staff", "worker", "user", "agent"],
        "customer": ["client", "buyer", "account", "user"],
        "product": ["item", "sku", "goods", "inventory"],
        "category": ["type", "group", "segment", "class"],
        "average": ["avg", "mean"],
        "monthly": ["month", "date"],
        "yearly": ["year", "date", "annual"],
        "daily": ["day", "date"],
        "payment": ["amount", "transaction", "charge", "invoice"],
        "shipping": ["shipment", "delivery", "tracking", "freight"],
        "discount": ["promo", "coupon", "rebate", "reduction"],
        "name": ["title", "label", "description"],
        "total": ["sum", "amount", "aggregate", "count"],
        "count": ["number", "total", "quantity"],
        "quantity": ["qty", "count", "amount", "units"],
        "percentage": ["percent", "rate", "ratio", "fraction"],
        "rank": ["position", "order", "rank", "rating"],
        "department": ["dept", "division", "team", "group", "unit"],
        "salary": ["wage", "pay", "compensation", "income", "earning"],
        "manager": ["supervisor", "boss", "lead", "head"],
        "country": ["nation", "region", "territory", "geo"],
        "city": ["town", "municipality", "location"],
        "email": ["mail", "contact", "address"],
        "phone": ["tel", "telephone", "mobile", "contact"],
        "created": ["created_at", "date", "timestamp", "registered"],
        "updated": ["modified", "changed", "last_modified"],
        "deleted": ["removed", "archived", "inactive"],
        "stock": ["inventory", "supply", "quantity", "available"],
        "supplier": ["vendor", "provider", "manufacturer"],
        "invoice": ["bill", "receipt", "statement", "charge"],
        "order": ["purchase", "transaction", "booking", "request"],
    }
    question_lower = question.lower()
    terms = [
        w for w in _re_link.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", question_lower) if len(w) >= 3 and w not in stopwords
    ]

    # N-gram extraction: combine adjacent terms into compound matches
    # "order items" should match "order_items" table, "customer address" → "customer_address"
    raw_terms = [
        w for w in _re_link.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", question_lower) if len(w) >= 2 and w not in stopwords
    ]
    ngram_terms: list[str] = []
    for i in range(len(raw_terms) - 1):
        bigram = f"{raw_terms[i]}_{raw_terms[i + 1]}"
        ngram_terms.append(bigram)
        if i + 2 < len(raw_terms):
            trigram = f"{raw_terms[i]}_{raw_terms[i + 1]}_{raw_terms[i + 2]}"
            ngram_terms.append(trigram)

    # Abbreviation expansion (common DB naming abbreviations → full words)
    _abbreviations: dict[str, list[str]] = {
        "cust": ["customer", "client"],
        "prod": ["product", "production"],
        "cat": ["category"],
        "qty": ["quantity"],
        "amt": ["amount"],
        "txn": ["transaction"],
        "inv": ["inventory", "invoice"],
        "dept": ["department"],
        "emp": ["employee"],
        "mgr": ["manager"],
        "addr": ["address"],
        "desc": ["description"],
        "num": ["number"],
        "dt": ["date"],
        "ts": ["timestamp"],
        "cnt": ["count"],
        "pct": ["percent", "percentage"],
        "avg": ["average"],
        "tot": ["total"],
        "bal": ["balance"],
        "acct": ["account"],
        "org": ["organization"],
        "loc": ["location"],
        "sku": ["product", "item"],
        "ref": ["reference"],
        "seq": ["sequence"],
        "idx": ["index"],
        "dim": ["dimension"],
        "fct": ["fact"],
        "stg": ["staging"],
    }

    # Expand terms with semantic synonyms (improves recall for Spider2.0)
    expanded_terms = list(terms)
    for term in terms:
        if term in _synonyms:
            for syn in _synonyms[term]:
                if syn not in expanded_terms:
                    expanded_terms.append(syn)
        # Abbreviation expansion
        if term in _abbreviations:
            for full_word in _abbreviations[term]:
                if full_word not in expanded_terms:
                    expanded_terms.append(full_word)
    # Add n-gram compound terms
    for ng in ngram_terms:
        if ng not in expanded_terms:
            expanded_terms.append(ng)
    terms = expanded_terms

    # Simple lemmatization for common suffixes (improves recall without NLTK dependency)
    def _lemmatize(word: str) -> str:
        """Reduce common English inflections to base form."""
        if word.endswith("ies") and len(word) > 4:
            return word[:-3] + "y"  # categories → category
        if word.endswith("ves") and len(word) > 4:
            return word[:-3] + "f"  # shelves → shelf
        if word.endswith("ses") and len(word) > 4:
            return word[:-2]  # addresses → address
        if word.endswith("es") and len(word) > 3:
            return word[:-2]  # taxes → tax
        if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
            return word[:-1]  # orders → order
        if word.endswith("ing") and len(word) > 5:
            return word[:-3]  # shipping → ship
        if word.endswith("ed") and len(word) > 4:
            return word[:-2]  # created → creat
        return word

    # Add lemmatized forms for better matching
    lemma_additions = []
    for term in terms:
        lemma = _lemmatize(term)
        if lemma != term and lemma not in terms and len(lemma) >= 3:
            lemma_additions.append(lemma)
    terms.extend(lemma_additions)

    # Question-type detection: boost relevant column types
    # Aggregation questions → boost numeric columns
    # Time questions → boost date/timestamp columns
    _agg_keywords = {
        "average",
        "avg",
        "sum",
        "total",
        "count",
        "max",
        "maximum",
        "min",
        "minimum",
        "mean",
        "median",
        "aggregate",
        "top",
        "bottom",
        "highest",
        "lowest",
        "most",
        "least",
    }
    _time_keywords = {
        "when",
        "date",
        "year",
        "month",
        "week",
        "day",
        "quarter",
        "recent",
        "latest",
        "oldest",
        "between",
        "before",
        "after",
        "during",
        "period",
    }
    _numeric_types = {
        "int",
        "integer",
        "bigint",
        "smallint",
        "float",
        "double",
        "decimal",
        "numeric",
        "real",
        "number",
        "money",
    }
    _time_types = {"date", "datetime", "timestamp", "timestamptz", "time"}

    question_words = set(question_lower.split())
    is_aggregation = bool(question_words & _agg_keywords)
    is_temporal = bool(question_words & _time_keywords)

    # Step 2: Score each table and column by relevance
    table_scores: dict[str, float] = {}
    column_scores: dict[str, dict[str, float]] = {}  # table_key -> {col_name: score}
    for table_key, table_data in filtered.items():
        score = 0.0
        col_scores: dict[str, float] = {}
        table_name_lower = table_data.get("name", "").lower()

        # Split table name into parts for compound matching (order_items -> ["order", "items"])
        table_name_parts = set(table_name_lower.split("_"))

        for term in terms:
            # Exact table name match (highest signal)
            if term == table_name_lower or term == table_name_lower.rstrip("s"):
                score += 10.0
            elif term in table_name_lower:
                score += 5.0
            # Singular/plural matching
            elif term + "s" == table_name_lower or term + "es" == table_name_lower:
                score += 8.0
            elif table_name_lower + "s" == term or table_name_lower + "es" == term:
                score += 8.0
            # Match against individual parts of compound table names
            elif term in table_name_parts or term.rstrip("s") in table_name_parts:
                score += 4.0

            # Column name matching — track per-column scores
            for col in table_data.get("columns", []):
                col_name_lower = col.get("name", "").lower()
                col_name = col.get("name", "")
                col_score = 0.0
                if term == col_name_lower:
                    col_score = 4.0
                elif term in col_name_lower:
                    col_score = 2.0
                # Check column comments
                comment = (col.get("comment") or "").lower()
                if term in comment:
                    col_score = max(col_score, 1.0)
                if col_score > 0:
                    col_scores[col_name] = col_scores.get(col_name, 0) + col_score
                    score += col_score

            # Table description/comment matching
            desc = (table_data.get("description") or "").lower()
            if term in desc:
                score += 2.0

        # N-gram matching: "order_items" bigram matches the table name directly
        # This catches compound terms like "customer address" → "customer_address"
        for ng in ngram_terms:
            if ng == table_name_lower:
                score += 12.0  # Exact compound match is very strong
            elif ng in table_name_lower:
                score += 6.0

        # Question-type boosting: prefer tables with relevant column types
        if is_aggregation and score > 0:
            numeric_cols = sum(
                1 for c in table_data.get("columns", []) if c.get("type", "").lower().split("(")[0] in _numeric_types
            )
            if numeric_cols > 0:
                score += min(numeric_cols * 0.5, 3.0)

        if is_temporal and score > 0:
            time_cols = sum(
                1
                for c in table_data.get("columns", [])
                if c.get("type", "").lower().split("(")[0] in _time_types
                or any(kw in c.get("name", "").lower() for kw in ("date", "time", "created", "updated"))
            )
            if time_cols > 0:
                score += min(time_cols * 0.5, 2.0)

        # Check cached sample values for value-based linking (RSL-SQL bidirectional approach)
        # EDBT 2026: value-based linking catches cases term-matching misses,
        # e.g., "show orders from California" matches sample value "California" in state column
        cached_samples = schema_cache.get_sample_values(name, table_key)
        if cached_samples:
            for col_name, sample_vals in cached_samples.items():
                for sv in sample_vals:
                    sv_lower = str(sv).lower()
                    if len(sv_lower) >= 3 and sv_lower in question_lower:
                        score += 6.0  # Strong signal: question mentions actual data value
                        col_scores[col_name] = col_scores.get(col_name, 0) + 4.0  # Also boost the column
                        break  # One match per column is enough

        # Boost tables with many FKs (hub tables are usually more relevant)
        fk_count = len(table_data.get("foreign_keys", []))
        if fk_count > 0 and score > 0:
            score += min(fk_count * 0.5, 3.0)  # Up to +3 for hub tables

        # Boost tables with column statistics (better schema = more useful for agent)
        has_stats = sum(1 for c in table_data.get("columns", []) if c.get("stats") or c.get("has_statistics"))
        if has_stats > 0 and score > 0:
            score += 1.0  # Tables with stats are more informative

        table_scores[table_key] = score
        column_scores[table_key] = col_scores

    # Step 3: FK-propagated scoring (Spider2.0 optimization)
    # Tables FK-connected to high-scoring tables get a fraction of that score.
    # This ensures join-path tables are included AND ordered by relevance.
    # Build reverse FK index first: table_name → [keys of tables that reference it]
    reverse_fk_index: dict[str, list[str]] = {}
    for key, table_data in filtered.items():
        for fk in table_data.get("foreign_keys", []):
            ref_table = fk.get("references_table", "")
            if ref_table not in reverse_fk_index:
                reverse_fk_index[ref_table] = []
            reverse_fk_index[ref_table].append(key)

    # Forward FK propagation: if table A (score 20) → references table B, B gets +20*0.3
    # Reverse FK propagation: if table C references table A, C gets +20*0.2
    fk_boost: dict[str, float] = {}
    for key, score in table_scores.items():
        if score <= 0:
            continue
        table_data = filtered.get(key, {})
        # Forward: A.customer_id → customers — boost customers
        for fk in table_data.get("foreign_keys", []):
            ref_table = fk.get("references_table", "")
            for candidate_key in filtered:
                if filtered[candidate_key].get("name", "") == ref_table and candidate_key != key:
                    fk_boost[candidate_key] = max(fk_boost.get(candidate_key, 0), score * 0.3)
                    break
        # Reverse: tables that reference this table — boost them
        table_name = table_data.get("name", "")
        for referring_key in reverse_fk_index.get(table_name, []):
            if referring_key in filtered and referring_key != key:
                fk_boost[referring_key] = max(fk_boost.get(referring_key, 0), score * 0.2)

    # Apply FK boosts to scores
    for key, boost in fk_boost.items():
        if table_scores.get(key, 0) == 0:
            table_scores[key] = boost  # FK-only tables get the boost as their score
        # Don't increase already-scored tables — they earned their score directly

    # Step 4: Select top tables by score
    scored_tables = sorted(table_scores.items(), key=lambda x: (-x[1], x[0]))
    linked_keys = set()

    # Small-schema bypass: include ALL tables when schema is small enough.
    # Per "The Death of Schema Linking?" (OpenReview): for schemas that fit
    # the context window, skipping schema linking yields higher accuracy
    # because no relevant table can be missed. #1 on BIRD benchmark (71.83%).
    if _small_schema:
        linked_keys = set(filtered.keys())
    else:
        # Include tables with score > 0 (now includes FK-propagated scores)
        for key, score in scored_tables:
            if score > 0 and len(linked_keys) < max_tables:
                linked_keys.add(key)

    # If no matches found, fall back to first N tables sorted by FK relevance
    if not linked_keys:

        def _fb_relevance(key: str) -> tuple:
            t = filtered[key]
            return (-len(t.get("foreign_keys", [])), -(t.get("row_count", 0) or 0), key)

        linked_keys = set(sorted(filtered.keys(), key=_fb_relevance)[: min(max_tables, 10)])

    # Build response
    linked_schema = {k: filtered[k] for k in sorted(linked_keys) if k in filtered}

    # ── Column pruning helper ──────────────────────────────────────────────
    # For each table, determine which columns to include.
    # Always include: PK columns, FK columns, FK-referenced columns, and
    # columns with relevance score > 0.
    # For high-scoring tables (>= 5.0), include ALL columns (they're clearly relevant).
    # For lower-scoring tables (FK-connected), only include structural + matched columns.
    #
    # RSL-SQL / EDBT 2026: "missing a column is fatal; extras are tolerable noise."
    # We err on the side of keeping columns, especially join-path columns.

    # Build a set of columns that are FK targets from linked tables
    # (e.g., if orders.customer_id → customers.id, then customers.id must be kept)
    _fk_target_cols: dict[str, set[str]] = {}
    for lk in linked_keys:
        if lk not in filtered:
            continue
        for fk in filtered[lk].get("foreign_keys", []):
            ref_table = fk.get("references_table", "")
            ref_col = fk.get("references_column", "")
            # Find the matching linked table key
            for candidate_key in linked_keys:
                if filtered.get(candidate_key, {}).get("name", "") == ref_table:
                    if candidate_key not in _fk_target_cols:
                        _fk_target_cols[candidate_key] = set()
                    _fk_target_cols[candidate_key].add(ref_col)
                    break

    def _prune_columns(table_key: str, table_data: dict) -> list[dict]:
        """Return only relevant columns for a table, keeping PKs and FKs always."""
        t_score = table_scores.get(table_key, 0)
        # High-relevance tables: keep all columns (the whole table matters)
        if t_score >= 5.0 or not prune_columns:
            return table_data.get("columns", [])

        col_relevance = column_scores.get(table_key, {})
        fk_cols = {fk.get("column", "") for fk in table_data.get("foreign_keys", [])}
        fk_targets = _fk_target_cols.get(table_key, set())

        kept = []
        for col in table_data.get("columns", []):
            col_name = col.get("name", "")
            # Always keep: PKs, FK columns, FK-target columns, and columns with question relevance
            if col.get("primary_key"):
                kept.append(col)
            elif col_name in fk_cols:
                kept.append(col)
            elif col_name in fk_targets:
                kept.append(col)
            elif col_relevance.get(col_name, 0) > 0:
                kept.append(col)
        # If pruning removed everything, keep all (safety)
        return kept if kept else table_data.get("columns", [])

    if format == "condensed":
        # Condensed DDL: minimal token usage — pruned columns, no annotations, compressed types
        condensed_lines = []
        total_cols_original = 0
        total_cols_kept = 0
        for key in sorted(linked_keys):
            if key not in filtered:
                continue
            t = filtered[key]
            table_name = f"{t.get('schema', '')}.{t.get('name', '')}"
            all_cols = t.get("columns", [])
            kept_cols = _prune_columns(key, t)
            total_cols_original += len(all_cols)
            total_cols_kept += len(kept_cols)
            col_parts = []
            pk_cols = []
            for col in kept_cols:
                ct = col.get("type", "TEXT").upper()
                ct = compress_type(ct)
                # Strip precision from types for brevity: VARCHAR(255) → VARCHAR
                if "(" in ct and ct.split("(")[0] in ("VARCHAR", "NVARCHAR", "CHAR", "DECIMAL", "NUMERIC"):
                    ct = ct.split("(")[0]
                nn = " NOT NULL" if not col.get("nullable", True) else ""
                col_parts.append(f"  {col['name']} {ct}{nn}")
                if col.get("primary_key"):
                    pk_cols.append(col["name"])
            if pk_cols:
                col_parts.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")
            for fk in t.get("foreign_keys", []):
                col_parts.append(
                    f"  FOREIGN KEY ({fk['column']}) REFERENCES {fk.get('references_table', '')}({fk.get('references_column', '')})"
                )
            pruned_note = ""
            if len(kept_cols) < len(all_cols):
                pruned_note = f" -- {len(all_cols) - len(kept_cols)} columns pruned"
            obj_kw = "CREATE VIEW" if t.get("type") == "view" else "CREATE TABLE"
            col_block = ",\n".join(col_parts)
            condensed_lines.append(f"{obj_kw} {table_name} (\n{col_block}\n);{pruned_note}")
        condensed_text = "\n\n".join(condensed_lines)
        reduction_pct = round((1 - total_cols_kept / max(total_cols_original, 1)) * 100)
        condensed_result: dict[str, Any] = {
            "connection_name": name,
            "question": question,
            "format": "condensed",
            "full_schema": _small_schema,
            "linked_tables": len(linked_keys),
            "total_tables": len(filtered),
            "columns_original": total_cols_original,
            "columns_kept": total_cols_kept,
            "column_reduction_pct": reduction_pct,
            "token_estimate": len(condensed_text) // 4,
            "scores": {k: round(table_scores.get(k, 0), 1) for k in sorted(linked_keys) if table_scores.get(k, 0) > 0},
            "ddl": condensed_text,
        }
        # Add join hints and dialect (shared with DDL format)
        _join_hints = _build_join_hints(linked_keys, filtered)
        if _join_hints:
            condensed_result["join_hints"] = _join_hints
        _dh = _DIALECT_HINTS.get(info.db_type)
        if _dh:
            condensed_result["dialect"] = _dh
        return condensed_result

    if format == "compact":
        lines = []
        for key in sorted(linked_keys):
            if key not in filtered:
                continue
            t = filtered[key]
            col_strs = []
            kept_cols = _prune_columns(key, t)
            for c in kept_cols:
                pk_flag = "*" if c.get("primary_key") else ""
                ct = c.get("type", "").upper()
                s = f"{c['name']}{pk_flag} {ct}"
                stats = c.get("stats", {})
                if stats.get("distinct_count"):
                    s += f"({stats['distinct_count']}d)"
                col_strs.append(s)
            if len(kept_cols) < len(t.get("columns", [])):
                col_strs.append(f"+{len(t['columns']) - len(kept_cols)} more")
            cols = ", ".join(col_strs)
            rc = t.get("row_count", 0)
            rc_str = f" ({rc:,} rows)" if rc else ""
            score = table_scores.get(key, 0)
            lines.append(f"{key}{rc_str} [score={score:.1f}]: {cols}")
        return {
            "connection_name": name,
            "question": question,
            "format": "compact",
            "full_schema": _small_schema,
            "linked_tables": len(linked_keys),
            "total_tables": len(filtered),
            "scores": {k: round(table_scores.get(k, 0), 1) for k in sorted(linked_keys) if table_scores.get(k, 0) > 0},
            "schema": "\n".join(lines),
        }

    if format == "json":
        return {
            "connection_name": name,
            "question": question,
            "format": "json",
            "full_schema": _small_schema,
            "linked_tables": len(linked_keys),
            "total_tables": len(filtered),
            "scores": {k: table_scores.get(k, 0) for k in sorted(linked_keys)},
            "tables": linked_schema,
        }

    # DDL format (default — preferred by Spider2.0 SOTA)
    ddl_lines = []
    for key in sorted(linked_keys):
        if key not in filtered:
            continue
        t = filtered[key]
        table_name = f"{t.get('schema', '')}.{t.get('name', '')}"
        # Table description as comment (semantic context for agent)
        table_desc = t.get("description", "")
        header = f"-- {table_desc}\n" if table_desc else ""
        col_parts = []
        pk_cols = []
        ddl_cols = _prune_columns(key, t)
        pruned_count = len(t.get("columns", [])) - len(ddl_cols)
        for col in ddl_cols:
            ct = col.get("type", "TEXT").upper()
            ct = TYPE_COMPRESSION_MAP.get(ct, ct)
            parts = [f"  {col['name']} {ct}"]
            if not col.get("nullable", True):
                parts.append("NOT NULL")
            # Column annotations for agent context
            annotations = []
            col_comment = col.get("comment", "")
            if col_comment:
                annotations.append(col_comment)
            # Column statistics help agent understand data shape
            stats = col.get("stats", {})
            if stats.get("distinct_count"):
                annotations.append(f"{stats['distinct_count']} distinct values")
            elif stats.get("distinct_fraction"):
                frac = abs(stats["distinct_fraction"])
                if frac >= 0.99:
                    annotations.append("unique")
                elif frac >= 0.5:
                    annotations.append("high cardinality")
            # Redshift/warehouse column-level optimization hints
            if col.get("dist_key"):
                annotations.append("DISTKEY")
            if col.get("sort_key_position"):
                annotations.append(f"SORTKEY#{col['sort_key_position']}")
            if col.get("low_cardinality"):
                annotations.append("low cardinality")
            # Inline sample values for low-cardinality string columns (Spider2.0 key technique)
            # Only for columns with <=50 distinct values — avoids wasting tokens on unique/high-card columns
            is_low_card = False
            dc = stats.get("distinct_count", 0) if stats else 0
            df = abs(stats.get("distinct_fraction", 0)) if stats else 0
            if dc and dc <= 50:
                is_low_card = True
            elif df and df < 0.05:
                is_low_card = True
            elif not stats:
                is_low_card = True  # No stats = show samples as hint

            if is_low_card:
                cached_samples = schema_cache.get_sample_values(name, key)
                if cached_samples and col["name"] in cached_samples:
                    sample_vals = cached_samples[col["name"]]
                    if len(sample_vals) <= 10:
                        annotations.append(f"e.g. {', '.join(repr(v) for v in sample_vals[:5])}")
            if annotations:
                parts.append(f"-- {'; '.join(annotations)}")
            col_parts.append(" ".join(parts))
            if col.get("primary_key"):
                pk_cols.append(col["name"])
        if pk_cols:
            col_parts.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")
        for fk in t.get("foreign_keys", []):
            col_parts.append(
                f"  FOREIGN KEY ({fk['column']}) REFERENCES {fk.get('references_table', '')}({fk.get('references_column', '')})"
            )
        rc = t.get("row_count", 0)
        # Build metadata comment
        meta_parts = []
        if rc:
            meta_parts.append(f"{rc:,} rows" if rc < 1_000_000 else f"{rc / 1_000_000:.1f}M rows")
        engine = t.get("engine", "")
        if engine:
            meta_parts.append(f"ENGINE={engine}")
        sorting = t.get("sorting_key", "")
        if sorting:
            meta_parts.append(f"ORDER BY({sorting})")
        diststyle = t.get("diststyle", "")
        if diststyle:
            meta_parts.append(f"DISTSTYLE={diststyle}")
        sortkey = t.get("sortkey", "")
        if sortkey:
            meta_parts.append(f"SORTKEY({sortkey})")
        clustering_key = t.get("clustering_key", "")
        if clustering_key:
            meta_parts.append(f"CLUSTER BY({clustering_key})")
        meta_parts.append(f"relevance={table_scores.get(key, 0):.1f}")
        if pruned_count > 0:
            meta_parts.append(f"{pruned_count} cols pruned")
        rc_comment = f" -- {', '.join(meta_parts)}"
        obj_kw = "CREATE VIEW" if t.get("type") == "view" else "CREATE TABLE"
        col_block = ",\n".join(col_parts)
        ddl_lines.append(f"{header}{obj_kw} {table_name} (\n{col_block}\n);{rc_comment}")

    ddl_text = "\n\n".join(ddl_lines)

    # Proactively fetch sample values for linked tables that lack them (background)
    # Next schema_link call will include inline samples in DDL annotations
    missing_samples = []
    string_types = {
        "character varying",
        "varchar",
        "text",
        "char",
        "character",
        "enum",
        "String",
        "VARCHAR",
        "TEXT",
        "CHAR",
        "NVARCHAR",
        "string",
    }
    for key in linked_keys:
        if key not in filtered:
            continue
        if schema_cache.get_sample_values(name, key) is not None:
            continue  # Already cached
        t = filtered[key]
        sample_cols = [
            c["name"]
            for c in t.get("columns", [])
            if c.get("type", "") in string_types or "char" in c.get("type", "").lower()
        ]
        if sample_cols:
            missing_samples.append((key, t, sample_cols[:10]))

    if missing_samples:
        try:
            conn_str = await store.get_connection_string(name)
            if conn_str:
                extras = await store.get_credential_extras(name)
                async with pool_manager.connection(
                    info.db_type, conn_str, credential_extras=extras, connection_name=name
                ) as connector:
                    for key, t, sample_cols in missing_samples[:5]:  # Cap at 5 tables
                        table_name = f"{t.get('schema', '')}.{t['name']}" if t.get("schema") else t["name"]
                        try:
                            values = await connector.get_sample_values(table_name, sample_cols, limit=5)
                            if values:
                                schema_cache.put_sample_values(name, key, values)
                        except Exception:
                            pass
        except Exception:
            pass  # Best-effort — don't fail the schema_link response

    # Build join hints and dialect info using extracted helpers
    join_hints = _build_join_hints(linked_keys, filtered)

    result: dict[str, Any] = {
        "connection_name": name,
        "question": question,
        "format": "ddl",
        "full_schema": _small_schema,
        "linked_tables": len(linked_keys),
        "total_tables": len(filtered),
        "token_estimate": len(ddl_text) // 4,
        "scores": {k: round(table_scores.get(k, 0), 1) for k in sorted(linked_keys) if table_scores.get(k, 0) > 0},
        "ddl": ddl_text,
    }
    if join_hints:
        result["join_hints"] = join_hints
    dialect = _DIALECT_HINTS.get(info.db_type)
    if dialect:
        result["dialect"] = dialect

    # Query-type-aware hints (ReFoRCE "format restriction" pattern)
    # Detect question type and provide SQL pattern guidance to reduce errors
    query_hints: list[str] = []
    _q = question_lower
    if is_aggregation:
        query_hints.append("Use GROUP BY for aggregations; include all non-aggregated SELECT columns")
    if any(w in _q for w in ("top", "highest", "lowest", "rank", "first", "best", "worst")):
        if info.db_type == "mssql":
            query_hints.append("Use TOP N instead of LIMIT; for ranking use ROW_NUMBER() OVER(...)")
        else:
            query_hints.append("Use ORDER BY ... LIMIT N for top-N queries; consider RANK()/ROW_NUMBER() for ties")
    if any(w in _q for w in ("percentage", "percent", "ratio", "share", "proportion")):
        query_hints.append("Use 100.0 * COUNT/SUM to avoid integer division; cast to DECIMAL if needed")
    if is_temporal:
        if info.db_type in ("postgres", "redshift"):
            query_hints.append("Use DATE_TRUNC('month', col) for time grouping; EXTRACT(YEAR FROM col) for year")
        elif info.db_type == "mysql":
            query_hints.append("Use DATE_FORMAT(col, '%Y-%m') for month grouping; YEAR(col), MONTH(col) for parts")
        elif info.db_type == "mssql":
            query_hints.append("Use FORMAT(col, 'yyyy-MM') or DATEPART(YEAR, col) for time grouping")
        elif info.db_type == "bigquery":
            query_hints.append("Use FORMAT_DATE('%Y-%m', col) or EXTRACT(YEAR FROM col) for time grouping")
        elif info.db_type == "snowflake":
            query_hints.append("Use DATE_TRUNC('MONTH', col) for time grouping; TO_CHAR(col, 'YYYY-MM')")
    if any(w in _q for w in ("distinct", "unique", "different")):
        query_hints.append("Use COUNT(DISTINCT col) for unique counts; SELECT DISTINCT for unique rows")
    if any(w in _q for w in ("compare", "versus", "vs", "difference", "change")):
        query_hints.append("Consider self-joins or window functions (LAG/LEAD) for comparisons")
    if any(w in _q for w in ("running", "cumulative", "rolling")):
        query_hints.append("Use SUM(...) OVER (ORDER BY ...) for running totals; ROWS BETWEEN for rolling windows")

    if query_hints:
        result["query_hints"] = query_hints

    return result
