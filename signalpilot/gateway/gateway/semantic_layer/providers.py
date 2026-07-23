"""Semantic-layer providers: discovery + reference-query construction for
Snowflake Semantic Views and Databricks (Unity Catalog) Metric Views.

Pure SQL-construction and output-parsing logic — connectors execute the SQL,
so everything here is unit-testable without a live warehouse.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _check_ident(name: str, *, what: str) -> str:
    """Validate a bare identifier (metric/dimension names come from user input)."""
    if not _IDENT_RE.match(name or ""):
        raise ValueError(f"invalid {what} identifier: {name!r}")
    return name


def _check_qualified(name: str, *, what: str, max_parts: int = 3) -> str:
    parts = (name or "").split(".")
    if not 1 <= len(parts) <= max_parts or not all(_IDENT_RE.match(p) for p in parts):
        raise ValueError(f"invalid {what} name: {name!r}")
    return name


@dataclass
class SemanticMetric:
    name: str
    expression: str | None = None
    description: str | None = None


@dataclass
class SemanticObject:
    """A semantic view (Snowflake) or metric view (Databricks)."""

    name: str  # qualified
    kind: str  # snowflake_semantic_view | databricks_metric_view
    metrics: list[SemanticMetric] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)


# ── Snowflake Semantic Views ─────────────────────────────────────────────────


class SnowflakeSemanticProvider:
    """Snowflake Semantic Views (GA 2025): SHOW/DESCRIBE SEMANTIC VIEW and the
    SEMANTIC_VIEW() table function."""

    kind = "snowflake_semantic_view"

    def list_views_sql(self, schema: str | None = None) -> str:
        if schema:
            _check_qualified(schema, what="schema", max_parts=2)
            return f"SHOW SEMANTIC VIEWS IN SCHEMA {schema}"
        return "SHOW SEMANTIC VIEWS"

    def parse_list_views(self, rows: list[dict]) -> list[str]:
        out = []
        for r in rows:
            name = r.get("name") or r.get("NAME")
            db = r.get("database_name") or r.get("DATABASE_NAME")
            schema = r.get("schema_name") or r.get("SCHEMA_NAME")
            if name and db and schema:
                out.append(f"{db}.{schema}.{name}")
            elif name:
                out.append(str(name))
        return out

    def describe_sql(self, view: str) -> str:
        _check_qualified(view, what="semantic view")
        return f"DESCRIBE SEMANTIC VIEW {view}"

    def parse_describe(self, view: str, rows: list[dict]) -> SemanticObject:
        """DESCRIBE SEMANTIC VIEW returns one row per object: object_kind in
        (TABLE, RELATIONSHIP, FACT, DIMENSION, METRIC), object_name, and a
        property/property_value pair (EXPRESSION, COMMENT, ...)."""
        obj = SemanticObject(name=view, kind=self.kind)
        metric_props: dict[str, dict] = {}
        for r in rows:
            kind = str(r.get("object_kind") or r.get("OBJECT_KIND") or "").upper()
            name = r.get("object_name") or r.get("OBJECT_NAME")
            prop = str(r.get("property") or r.get("PROPERTY") or "").upper()
            value = r.get("property_value") or r.get("PROPERTY_VALUE")
            if not name:
                continue
            if kind == "METRIC":
                entry = metric_props.setdefault(str(name), {})
                if prop == "EXPRESSION":
                    entry["expression"] = value
                elif prop == "COMMENT":
                    entry["description"] = value
            elif kind == "DIMENSION":
                if str(name) not in obj.dimensions:
                    obj.dimensions.append(str(name))
        obj.metrics = [
            SemanticMetric(name=n, expression=p.get("expression"), description=p.get("description"))
            for n, p in metric_props.items()
        ]
        return obj

    def reference_query(
        self,
        view: str,
        *,
        metrics: list[str],
        dimensions: list[str],
    ) -> str:
        """SELECT * FROM SEMANTIC_VIEW(<view> METRICS ... DIMENSIONS ...)

        Metric/dimension references may be logical-table-qualified
        (orders.total_revenue) — the documented Semantic View form.
        """
        _check_qualified(view, what="semantic view")
        for m in metrics:
            _check_qualified(m, what="metric", max_parts=2)
        for d in dimensions:
            _check_qualified(d, what="dimension", max_parts=2)
        if not metrics:
            raise ValueError("at least one metric required")
        clauses = [view, f"METRICS {', '.join(metrics)}"]
        if dimensions:
            clauses.append(f"DIMENSIONS {', '.join(dimensions)}")
        return f"SELECT * FROM SEMANTIC_VIEW({' '.join(clauses)})"


# ── Databricks Metric Views ──────────────────────────────────────────────────


class DatabricksMetricProvider:
    """Databricks Unity Catalog Metric Views: discovered via information_schema,
    described via DESCRIBE TABLE EXTENDED (YAML definition), queried with
    MEASURE() aggregation."""

    kind = "databricks_metric_view"

    def list_views_sql(self, schema: str | None = None) -> str:
        base = (
            "SELECT table_catalog, table_schema, table_name FROM information_schema.views"
        )
        if schema:
            _check_qualified(schema, what="schema", max_parts=2)
            parts = schema.split(".")
            if len(parts) == 2:
                return base + f" WHERE table_catalog = '{parts[0]}' AND table_schema = '{parts[1]}'"
            return base + f" WHERE table_schema = '{parts[0]}'"
        return base

    def parse_list_views(self, rows: list[dict]) -> list[str]:
        out = []
        for r in rows:
            cat = r.get("table_catalog")
            sch = r.get("table_schema")
            name = r.get("table_name")
            if cat and sch and name:
                out.append(f"{cat}.{sch}.{name}")
        return out

    def describe_sql(self, view: str) -> str:
        _check_qualified(view, what="metric view")
        return f"DESCRIBE TABLE EXTENDED {view}"

    def parse_describe(self, view: str, rows: list[dict]) -> SemanticObject | None:
        """DESCRIBE TABLE EXTENDED on a metric view includes a 'Type' row of
        METRIC_VIEW and a 'View Text' / '# Metric View Definition' YAML block
        listing measures and dimensions. Returns None when not a metric view."""
        obj = SemanticObject(name=view, kind=self.kind)
        is_metric_view = False
        yaml_text = ""
        for r in rows:
            col = str(r.get("col_name") or "").strip()
            val = str(r.get("data_type") or "").strip()
            if col.lower() == "type" and "metric" in val.lower():
                is_metric_view = True
            if col.lower() in ("view text", "view_definition", "# metric view definition"):
                yaml_text = val
        if not is_metric_view:
            return None
        # Minimal YAML scrape: measures/dimensions entries `- name: x` with
        # optional `expr: ...`. A full YAML parse is deliberately avoided —
        # the definition may embed SQL fragments that break strict parsing.
        # Section state resets only on TOP-LEVEL keys (no indentation) so
        # per-item properties (comment:, synonyms:, format:, window:, ...)
        # don't truncate the rest of the section.
        section = None
        for line in yaml_text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("measures:"):
                section = "measures"
                continue
            if stripped.lower().startswith("dimensions:"):
                section = "dimensions"
                continue
            if re.match(r"^[A-Za-z_]+:", line):  # unindented = new top-level key
                section = None
                continue
            m = re.match(r"^-\s*name:\s*(.+)$", stripped, re.IGNORECASE)
            if m and section:
                name = m.group(1).strip().strip("'\"")
                if section == "measures":
                    obj.metrics.append(SemanticMetric(name=name))
                else:
                    obj.dimensions.append(name)
                continue
            m = re.match(r"^expr:\s*(.+)$", stripped, re.IGNORECASE)
            if m and section == "measures" and obj.metrics:
                obj.metrics[-1].expression = m.group(1).strip().strip("'\"")
        return obj

    def reference_query(
        self,
        view: str,
        *,
        metrics: list[str],
        dimensions: list[str],
    ) -> str:
        """SELECT dims..., MEASURE(m) ... FROM view GROUP BY dims"""
        _check_qualified(view, what="metric view")
        for m in metrics:
            _check_ident(m, what="metric")
        for d in dimensions:
            _check_ident(d, what="dimension")
        if not metrics:
            raise ValueError("at least one metric required")
        select_parts = [f"`{d}`" for d in dimensions] + [
            f"MEASURE(`{m}`) AS `{m}`" for m in metrics
        ]
        sql = f"SELECT {', '.join(select_parts)} FROM {view}"
        if dimensions:
            sql += f" GROUP BY {', '.join(f'`{d}`' for d in dimensions)}"
        return sql


def provider_for_db_type(db_type: str):
    if db_type == "snowflake":
        return SnowflakeSemanticProvider()
    if db_type == "databricks":
        return DatabricksMetricProvider()
    return None
