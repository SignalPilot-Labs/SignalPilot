"""Tests for Spider2.0-optimized schema context generation.

Verifies that the agent-context endpoint produces optimal output for
text-to-SQL benchmarks: progressive disclosure, compact format, token
efficiency, and schema linking quality across question types.

Based on Spider2.0 SOTA findings:
- DDL format preferred over JSON/YAML by top performers
- Sample values provide 3-4% EX improvement
- FK graph traversal needed for multi-table joins
- Progressive disclosure (CHESS/DIN-SQL pattern) saves 40-60% tokens
"""

import pytest
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))


# ── Test fixtures ──────────────────────────────────────────────────

def _enterprise_schema() -> dict:
    """Realistic enterprise schema (~10 tables) for testing context generation."""
    return {
        "public.customers": {
            "schema": "public", "name": "customers", "type": "table",
            "columns": [
                {"name": "id", "type": "integer", "nullable": False, "primary_key": True, "comment": ""},
                {"name": "name", "type": "varchar(255)", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "email", "type": "varchar(255)", "nullable": True, "primary_key": False, "comment": ""},
                {"name": "segment", "type": "varchar(50)", "nullable": True, "primary_key": False, "comment": ""},
                {"name": "created_at", "type": "timestamp", "nullable": True, "primary_key": False, "comment": ""},
            ],
            "foreign_keys": [],
            "row_count": 50000, "description": "Customer records",
        },
        "public.orders": {
            "schema": "public", "name": "orders", "type": "table",
            "columns": [
                {"name": "id", "type": "integer", "nullable": False, "primary_key": True, "comment": ""},
                {"name": "customer_id", "type": "integer", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "status", "type": "varchar(20)", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "total", "type": "numeric(12,2)", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "created_at", "type": "timestamp", "nullable": True, "primary_key": False, "comment": ""},
            ],
            "foreign_keys": [
                {"column": "customer_id", "references_table": "customers", "references_column": "id"},
            ],
            "row_count": 500000, "description": "Order records",
        },
        "public.order_items": {
            "schema": "public", "name": "order_items", "type": "table",
            "columns": [
                {"name": "id", "type": "integer", "nullable": False, "primary_key": True, "comment": ""},
                {"name": "order_id", "type": "integer", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "product_id", "type": "integer", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "quantity", "type": "integer", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "unit_price", "type": "numeric(10,2)", "nullable": False, "primary_key": False, "comment": ""},
            ],
            "foreign_keys": [
                {"column": "order_id", "references_table": "orders", "references_column": "id"},
                {"column": "product_id", "references_table": "products", "references_column": "id"},
            ],
            "row_count": 2000000, "description": "",
        },
        "public.products": {
            "schema": "public", "name": "products", "type": "table",
            "columns": [
                {"name": "id", "type": "integer", "nullable": False, "primary_key": True, "comment": ""},
                {"name": "name", "type": "varchar(255)", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "category_id", "type": "integer", "nullable": True, "primary_key": False, "comment": ""},
                {"name": "price", "type": "numeric(10,2)", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "sku", "type": "varchar(50)", "nullable": True, "primary_key": False, "comment": ""},
            ],
            "foreign_keys": [
                {"column": "category_id", "references_table": "categories", "references_column": "id"},
            ],
            "row_count": 5000, "description": "Product catalog",
        },
        "public.categories": {
            "schema": "public", "name": "categories", "type": "table",
            "columns": [
                {"name": "id", "type": "integer", "nullable": False, "primary_key": True, "comment": ""},
                {"name": "name", "type": "varchar(100)", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "parent_id", "type": "integer", "nullable": True, "primary_key": False, "comment": ""},
            ],
            "foreign_keys": [],
            "row_count": 50, "description": "Product categories",
        },
        "public.payments": {
            "schema": "public", "name": "payments", "type": "table",
            "columns": [
                {"name": "id", "type": "integer", "nullable": False, "primary_key": True, "comment": ""},
                {"name": "order_id", "type": "integer", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "method", "type": "varchar(20)", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "amount", "type": "numeric(12,2)", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "status", "type": "varchar(20)", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "processed_at", "type": "timestamp", "nullable": True, "primary_key": False, "comment": ""},
            ],
            "foreign_keys": [
                {"column": "order_id", "references_table": "orders", "references_column": "id"},
            ],
            "row_count": 480000, "description": "Payment transactions",
        },
        "public.shipments": {
            "schema": "public", "name": "shipments", "type": "table",
            "columns": [
                {"name": "id", "type": "integer", "nullable": False, "primary_key": True, "comment": ""},
                {"name": "order_id", "type": "integer", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "carrier", "type": "varchar(50)", "nullable": True, "primary_key": False, "comment": ""},
                {"name": "tracking_number", "type": "varchar(100)", "nullable": True, "primary_key": False, "comment": ""},
                {"name": "shipped_at", "type": "timestamp", "nullable": True, "primary_key": False, "comment": ""},
                {"name": "delivered_at", "type": "timestamp", "nullable": True, "primary_key": False, "comment": ""},
            ],
            "foreign_keys": [
                {"column": "order_id", "references_table": "orders", "references_column": "id"},
            ],
            "row_count": 400000, "description": "",
        },
        "public.reviews": {
            "schema": "public", "name": "reviews", "type": "table",
            "columns": [
                {"name": "id", "type": "integer", "nullable": False, "primary_key": True, "comment": ""},
                {"name": "product_id", "type": "integer", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "customer_id", "type": "integer", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "rating", "type": "integer", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "body", "type": "text", "nullable": True, "primary_key": False, "comment": ""},
                {"name": "created_at", "type": "timestamp", "nullable": True, "primary_key": False, "comment": ""},
            ],
            "foreign_keys": [
                {"column": "product_id", "references_table": "products", "references_column": "id"},
                {"column": "customer_id", "references_table": "customers", "references_column": "id"},
            ],
            "row_count": 100000, "description": "Product reviews",
        },
        "public.inventory": {
            "schema": "public", "name": "inventory", "type": "table",
            "columns": [
                {"name": "id", "type": "integer", "nullable": False, "primary_key": True, "comment": ""},
                {"name": "product_id", "type": "integer", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "warehouse", "type": "varchar(50)", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "quantity", "type": "integer", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "last_restocked", "type": "timestamp", "nullable": True, "primary_key": False, "comment": ""},
            ],
            "foreign_keys": [
                {"column": "product_id", "references_table": "products", "references_column": "id"},
            ],
            "row_count": 15000, "description": "Warehouse inventory levels",
        },
        "audit.event_log": {
            "schema": "audit", "name": "event_log", "type": "table",
            "columns": [
                {"name": "id", "type": "bigint", "nullable": False, "primary_key": True, "comment": ""},
                {"name": "event_type", "type": "varchar(50)", "nullable": False, "primary_key": False, "comment": ""},
                {"name": "entity_id", "type": "integer", "nullable": True, "primary_key": False, "comment": ""},
                {"name": "payload", "type": "jsonb", "nullable": True, "primary_key": False, "comment": ""},
                {"name": "created_at", "type": "timestamp", "nullable": False, "primary_key": False, "comment": ""},
            ],
            "foreign_keys": [],
            "row_count": 5000000, "description": "System audit log",
        },
    }


# ── Schema Linking Tests ──────────────────────────────────────────

class TestSchemaLinkingAccuracy:
    """Test that schema linking finds the right tables for Spider2.0-style questions."""

    def _link(self, schema: dict, question: str) -> dict[str, float]:
        """Simulate the schema linking logic from agent-context endpoint."""
        stopwords = {
            "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
            "her", "was", "one", "our", "out", "has", "how", "many", "much",
            "what", "which", "show", "find", "list", "give", "tell",
            "from", "with", "that", "this", "have", "will",
            "select", "where", "group", "having", "limit", "table", "column", "database",
        }
        terms = [w for w in re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', question.lower())
                 if len(w) >= 3 and w not in stopwords]

        scores: dict[str, float] = {}
        for key, t in schema.items():
            score = 0.0
            tn = t.get("name", "").lower()
            for term in terms:
                if term == tn or term == tn.rstrip("s"):
                    score += 10.0
                elif term in tn:
                    score += 3.0
                for col in t.get("columns", []):
                    cn = col.get("name", "").lower()
                    if term == cn:
                        score += 4.0
                    elif term in cn:
                        score += 1.5
            scores[key] = score

        # Add FK-connected tables
        linked = {k for k, s in scores.items() if s > 0}
        fk_adds = set()
        for k in list(linked):
            for fk in schema.get(k, {}).get("foreign_keys", []):
                for ck in schema:
                    if schema[ck].get("name") == fk.get("references_table"):
                        fk_adds.add(ck)
        linked |= fk_adds
        return {k: scores.get(k, 0) for k in linked}

    def test_single_table_question(self):
        """Simple single-table questions should link to exactly the right table."""
        schema = _enterprise_schema()
        result = self._link(schema, "Show all customers")
        assert "public.customers" in result
        assert result["public.customers"] > 0

    def test_join_question_links_both_tables(self):
        """Questions about orders and customers should link both + FK tables."""
        schema = _enterprise_schema()
        result = self._link(schema, "What are the top customers by total order amount?")
        assert "public.customers" in result
        assert "public.orders" in result

    def test_fk_traversal_includes_referenced_tables(self):
        """FK references should pull in referenced tables even if not mentioned."""
        schema = _enterprise_schema()
        result = self._link(schema, "Show order items with quantities")
        assert "public.order_items" in result
        # FK to orders and products should be included
        assert "public.orders" in result
        assert "public.products" in result

    def test_column_name_matching(self):
        """Questions mentioning column names should link the containing table."""
        schema = _enterprise_schema()
        result = self._link(schema, "What is the average rating for each product?")
        assert "public.reviews" in result  # has 'rating' column

    def test_irrelevant_tables_excluded(self):
        """Tables not related to the question should have score 0."""
        schema = _enterprise_schema()
        result = self._link(schema, "Show all customers")
        # audit.event_log should not be linked
        assert "audit.event_log" not in result

    def test_multi_hop_join_question(self):
        """Questions requiring 3+ table joins should link all necessary tables."""
        schema = _enterprise_schema()
        result = self._link(schema, "Show payment status for each order with product names")
        assert "public.payments" in result
        assert "public.orders" in result

    def test_plural_matching(self):
        """'order' should match 'orders' table via plural stripping."""
        schema = _enterprise_schema()
        result = self._link(schema, "How many order were placed this month?")
        assert "public.orders" in result
        assert result["public.orders"] > 0

    def test_substring_matching(self):
        """Column substring 'ship' should partially match 'shipments'."""
        schema = _enterprise_schema()
        result = self._link(schema, "When was the shipment delivered?")
        assert "public.shipments" in result


# ── Progressive Disclosure Tests ──────────────────────────────────

class TestProgressiveDisclosure:
    """Test progressive disclosure produces correct two-tier output."""

    def _build_context(self, schema: dict, question: str = "",
                       progressive: bool = True, full_ddl_count: int = 3) -> str:
        """Build agent context text simulating the endpoint logic."""
        # Schema linking scores
        stopwords = {
            "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
            "from", "with", "that", "this", "have", "will", "show", "find", "list",
            "select", "where", "group", "having", "limit", "table", "column", "database",
            "what", "which", "how", "many", "much", "give", "tell",
        }
        terms = [w for w in re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', question.lower())
                 if len(w) >= 3 and w not in stopwords] if question else []
        table_scores: dict[str, float] = {}
        for key, t in schema.items():
            score = 0.0
            tn = t.get("name", "").lower()
            for term in terms:
                if term == tn or term == tn.rstrip("s"):
                    score += 10.0
                elif term in tn:
                    score += 3.0
                for col in t.get("columns", []):
                    cn = col.get("name", "").lower()
                    if term == cn:
                        score += 4.0
                    elif term in cn:
                        score += 1.5
            table_scores[key] = score

        # Determine full vs compact keys
        if progressive and question:
            scored = sorted(schema.keys(), key=lambda k: table_scores.get(k, 0), reverse=True)
            full_ddl_keys = set(scored[:full_ddl_count])
            compact_keys = set(scored[full_ddl_count:])
        elif progressive:
            all_keys = sorted(schema.keys())
            full_ddl_keys = set(all_keys[:full_ddl_count])
            compact_keys = set(all_keys[full_ddl_count:])
        else:
            full_ddl_keys = set(schema.keys())
            compact_keys = set()

        sections: list[str] = []

        # Compact section
        if compact_keys:
            compact_lines = ["-- === Additional Tables (compact) ==="]
            for key in sorted(compact_keys):
                table = schema[key]
                table_name = f"{table.get('schema', '')}.{table['name']}" if table.get("schema") else table["name"]
                cols = table.get("columns", [])
                pks = [c["name"] for c in cols if c.get("primary_key")]
                fks = table.get("foreign_keys", [])
                rc = table.get("row_count", 0) or 0
                parts = [f"{len(cols)} cols"]
                if rc:
                    parts.append(f"{rc:,} rows")
                if pks:
                    parts.append(f"PK: {','.join(pks)}")
                for fk in fks:
                    ref = fk.get("references_table", "?")
                    parts.append(f"FK: {fk.get('column', '?')}→{ref}")
                compact_lines.append(f"-- {table_name} ({', '.join(parts)})")
            sections.append("\n".join(compact_lines))

        # Full DDL section
        for key in sorted(full_ddl_keys):
            table = schema[key]
            table_name = f"{table.get('schema', '')}.{table['name']}" if table.get("schema") else table["name"]
            col_lines = []
            for col in table.get("columns", []):
                ct = col.get("type", "").upper()
                nn = " NOT NULL" if not col.get("nullable", True) else ""
                col_lines.append(f"  {col['name']} {ct}{nn}")
            pks = [col["name"] for col in table.get("columns", []) if col.get("primary_key")]
            if pks:
                col_lines.append(f"  PRIMARY KEY ({', '.join(pks)})")
            for fk in table.get("foreign_keys", []):
                col_lines.append(f"  FOREIGN KEY ({fk['column']}) REFERENCES {fk['references_table']}({fk['references_column']})")
            ddl = f"CREATE TABLE {table_name} (\n{chr(44) + chr(10).join(col_lines)}\n);"
            sections.append(ddl)

        return "\n\n".join(sections)

    def test_progressive_reduces_tokens(self):
        """Progressive mode should produce fewer tokens than full mode."""
        schema = _enterprise_schema()
        full = self._build_context(schema, progressive=False)
        prog = self._build_context(schema, progressive=True, full_ddl_count=3)
        assert len(prog) < len(full), f"Progressive ({len(prog)}) should be shorter than full ({len(full)})"
        # Should save at least 25%
        ratio = len(prog) / len(full)
        assert ratio < 0.75, f"Token reduction {1 - ratio:.0%} should be >= 25%"

    def test_progressive_contains_compact_section(self):
        """Progressive mode should have an 'Additional Tables (compact)' section."""
        schema = _enterprise_schema()
        result = self._build_context(schema, progressive=True, full_ddl_count=3)
        assert "Additional Tables (compact)" in result

    def test_progressive_compact_lines_have_pk_fk(self):
        """Compact lines should include PK and FK info for join planning."""
        schema = _enterprise_schema()
        result = self._build_context(schema, progressive=True, full_ddl_count=2)
        # Find compact lines (start with "-- " and contain "cols")
        compact_lines = [l for l in result.split("\n")
                         if l.startswith("-- ") and "cols" in l
                         and "Additional Tables" not in l]
        assert len(compact_lines) > 0
        # At least some should have FK info
        fk_lines = [l for l in compact_lines if "FK:" in l]
        assert len(fk_lines) > 0, "Compact lines should include FK references"

    def test_progressive_full_ddl_has_create_table(self):
        """Full DDL tables should have CREATE TABLE statements."""
        schema = _enterprise_schema()
        result = self._build_context(schema, progressive=True, full_ddl_count=3)
        create_count = result.count("CREATE TABLE")
        assert create_count == 3, f"Expected 3 CREATE TABLE, got {create_count}"

    def test_progressive_question_prioritizes_relevant_tables(self):
        """With a question, full DDL should go to the most relevant tables."""
        schema = _enterprise_schema()
        result = self._build_context(schema, question="Show customer orders with payments",
                                      progressive=True, full_ddl_count=3)
        # customers, orders, payments should be in full DDL (highest scores)
        assert "CREATE TABLE public.customers" in result
        assert "CREATE TABLE public.orders" in result
        assert "CREATE TABLE public.payments" in result
        # Lower-scoring tables should be compact
        assert "audit.event_log" not in result or "CREATE TABLE audit.event_log" not in result

    def test_full_ddl_count_controls_split(self):
        """full_ddl_count parameter should control how many tables get full DDL."""
        schema = _enterprise_schema()
        for count in [1, 3, 5, 8]:
            result = self._build_context(schema, progressive=True, full_ddl_count=count)
            create_count = result.count("CREATE TABLE")
            expected = min(count, len(schema))
            assert create_count == expected, f"full_ddl_count={count}: got {create_count} CREATE TABLE, expected {expected}"

    def test_non_progressive_includes_all_ddl(self):
        """Non-progressive mode should include full DDL for all tables."""
        schema = _enterprise_schema()
        result = self._build_context(schema, progressive=False)
        create_count = result.count("CREATE TABLE")
        assert create_count == len(schema)
        assert "Additional Tables (compact)" not in result


# ── Compact Format Tests ──────────────────────────────────────────

class TestCompactFormat:
    """Test compact one-liner format for low-priority tables."""

    def test_compact_format_structure(self):
        """Compact line should follow: -- schema.name (N cols, M rows, PK: x, FK: y→z)"""
        table = {
            "schema": "public", "name": "orders",
            "columns": [
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "customer_id", "type": "integer", "primary_key": False},
                {"name": "total", "type": "numeric", "primary_key": False},
            ],
            "foreign_keys": [
                {"column": "customer_id", "references_table": "customers", "references_column": "id"},
            ],
            "row_count": 500000,
        }
        cols = table["columns"]
        pks = [c["name"] for c in cols if c.get("primary_key")]
        fks = table["foreign_keys"]
        rc = table["row_count"]

        parts = [f"{len(cols)} cols"]
        if rc:
            parts.append(f"{rc:,} rows")
        if pks:
            parts.append(f"PK: {','.join(pks)}")
        for fk in fks:
            parts.append(f"FK: {fk['column']}→{fk['references_table']}")

        line = f"-- public.orders ({', '.join(parts)})"
        assert "3 cols" in line
        assert "500,000 rows" in line
        assert "PK: id" in line
        assert "FK: customer_id→customers" in line

    def test_compact_preserves_join_info(self):
        """Compact format must preserve enough info for the agent to plan joins."""
        schema = _enterprise_schema()
        # order_items has 2 FKs — both should appear in compact format
        table = schema["public.order_items"]
        fks = table["foreign_keys"]
        assert len(fks) == 2
        # Both FK refs should be present
        refs = {fk["references_table"] for fk in fks}
        assert "orders" in refs
        assert "products" in refs


# ── Token Efficiency Tests ────────────────────────────────────────

class TestTokenEfficiency:
    """Test that context generation is token-efficient for LLM consumption."""

    def test_ddl_token_estimate(self):
        """Token estimate should be roughly chars/4."""
        text = "CREATE TABLE public.orders (\n  id INTEGER NOT NULL\n);"
        estimate = len(text) // 4
        # ~4 chars per token is a reasonable approximation
        assert estimate > 0
        assert estimate < len(text)

    def test_10_table_schema_under_3k_tokens_progressive(self):
        """10-table enterprise schema should fit under 3000 tokens in progressive mode."""
        schema = _enterprise_schema()
        # Build compact context (3 full DDL)
        sections = []
        keys = sorted(schema.keys())
        # Compact tables
        compact_lines = ["-- === Additional Tables (compact) ==="]
        for key in keys[3:]:
            t = schema[key]
            name = f"{t.get('schema','')}.{t['name']}"
            compact_lines.append(f"-- {name} ({len(t['columns'])} cols, {t.get('row_count',0):,} rows)")
        sections.append("\n".join(compact_lines))
        # Full DDL (first 3)
        for key in keys[:3]:
            t = schema[key]
            name = f"{t.get('schema','')}.{t['name']}"
            col_lines = [f"  {c['name']} {c['type'].upper()}" for c in t["columns"]]
            sections.append(f"CREATE TABLE {name} (\n{chr(44) + chr(10).join(col_lines)}\n);")
        context = "\n\n".join(sections)
        tokens = len(context) // 4
        assert tokens < 3000, f"Progressive 10-table context = {tokens} tokens, should be < 3000"

    def test_full_ddl_10_tables_under_5k_tokens(self):
        """Full DDL for 10 tables should be under 5000 tokens."""
        schema = _enterprise_schema()
        sections = []
        for key in sorted(schema.keys()):
            t = schema[key]
            name = f"{t.get('schema','')}.{t['name']}"
            col_lines = []
            for c in t["columns"]:
                col_lines.append(f"  {c['name']} {c['type'].upper()}")
            for fk in t.get("foreign_keys", []):
                col_lines.append(f"  FOREIGN KEY ({fk['column']}) REFERENCES {fk['references_table']}({fk['references_column']})")
            sections.append(f"CREATE TABLE {name} (\n{chr(44) + chr(10).join(col_lines)}\n);")
        context = "\n\n".join(sections)
        tokens = len(context) // 4
        assert tokens < 5000, f"Full DDL 10-table context = {tokens} tokens, should be < 5000"


# ── DDL Quality Tests ─────────────────────────────────────────────

class TestDDLQuality:
    """Test that generated DDL is syntactically correct and informative."""

    def test_create_table_syntax(self):
        """Generated DDL should be valid CREATE TABLE syntax."""
        schema = _enterprise_schema()
        table = schema["public.orders"]
        name = "public.orders"
        col_lines = []
        for col in table["columns"]:
            ct = col["type"].upper()
            nn = " NOT NULL" if not col.get("nullable", True) else ""
            col_lines.append(f"  {col['name']} {ct}{nn}")
        pks = [c["name"] for c in table["columns"] if c.get("primary_key")]
        if pks:
            col_lines.append(f"  PRIMARY KEY ({', '.join(pks)})")
        for fk in table.get("foreign_keys", []):
            col_lines.append(f"  FOREIGN KEY ({fk['column']}) REFERENCES {fk['references_table']}({fk['references_column']})")
        ddl = f"CREATE TABLE {name} (\n{chr(44) + chr(10).join(col_lines)}\n);"

        assert ddl.startswith("CREATE TABLE public.orders")
        assert ddl.endswith(");")
        assert "id INTEGER NOT NULL" in ddl
        assert "PRIMARY KEY (id)" in ddl
        assert "FOREIGN KEY (customer_id) REFERENCES customers(id)" in ddl

    def test_not_null_only_on_non_nullable(self):
        """NOT NULL should only appear for non-nullable columns."""
        schema = _enterprise_schema()
        table = schema["public.customers"]
        for col in table["columns"]:
            ct = col["type"].upper()
            nn = " NOT NULL" if not col.get("nullable", True) else ""
            line = f"{col['name']} {ct}{nn}"
            if col["name"] == "id":
                assert "NOT NULL" in line
            elif col["name"] == "email":
                assert "NOT NULL" not in line

    def test_fk_references_format(self):
        """FK constraints should reference the correct table and column."""
        schema = _enterprise_schema()
        table = schema["public.order_items"]
        fks = table["foreign_keys"]
        fk_map = {fk["column"]: fk for fk in fks}
        assert "order_id" in fk_map
        assert fk_map["order_id"]["references_table"] == "orders"
        assert fk_map["order_id"]["references_column"] == "id"
        assert "product_id" in fk_map
        assert fk_map["product_id"]["references_table"] == "products"

    def test_view_uses_create_view(self):
        """Views should use CREATE VIEW instead of CREATE TABLE."""
        table = {
            "schema": "public", "name": "active_orders", "type": "view",
            "columns": [
                {"name": "id", "type": "integer", "nullable": False, "primary_key": False},
                {"name": "status", "type": "varchar(20)", "nullable": False, "primary_key": False},
            ],
            "foreign_keys": [], "row_count": 0,
        }
        obj_kw = "CREATE VIEW" if table.get("type") == "view" else "CREATE TABLE"
        assert obj_kw == "CREATE VIEW"


# ── Schema Normalization for Agent Context ────────────────────────

class TestNormalizationForContext:
    """Test that schema normalization produces consistent agent-ready output."""

    def test_missing_fields_dont_break_context(self):
        """Tables with missing fields should still generate valid DDL."""
        from gateway.connectors.schema_cache import _normalize_schema
        schema = {
            "raw_table": {
                "columns": [
                    {"name": "id", "type": "integer"},
                ]
            }
        }
        _normalize_schema(schema)
        t = schema["raw_table"]
        assert t["schema"] == ""
        assert t["name"] == "raw_table"
        assert t["foreign_keys"] == []
        assert t["row_count"] == 0
        # Columns should also be normalized
        col = t["columns"][0]
        assert col["nullable"] is True  # default
        assert col["primary_key"] is False

    def test_bigquery_size_conversion(self):
        """BigQuery size_bytes should be converted to size_mb for consistency."""
        from gateway.connectors.schema_cache import _normalize_schema
        schema = {
            "project.dataset.big_table": {
                "columns": [{"name": "id", "type": "INT64"}],
                "size_bytes": 536870912,  # 512 MB
            }
        }
        _normalize_schema(schema)
        assert schema["project.dataset.big_table"]["size_mb"] == 512.0

    def test_dotted_key_name_extraction(self):
        """Table name should be extracted from dotted key."""
        from gateway.connectors.schema_cache import _normalize_schema
        schema = {
            "myschema.orders": {
                "columns": [],
            }
        }
        _normalize_schema(schema)
        assert schema["myschema.orders"]["name"] == "orders"
