"""MetricProof tests: semantic-layer providers (SQL construction + output
parsing) and the conformance comparison engine. All pure — no warehouse."""

from __future__ import annotations

import math

import pytest

from gateway.semantic_layer.conformance import (
    compare_metric,
    render_conformance_markdown,
)
from gateway.semantic_layer.providers import (
    DatabricksMetricProvider,
    SnowflakeSemanticProvider,
    provider_for_db_type,
)


class TestSnowflakeProvider:
    p = SnowflakeSemanticProvider()

    def test_list_and_parse(self):
        assert self.p.list_views_sql() == "SHOW SEMANTIC VIEWS"
        assert self.p.list_views_sql("db.analytics") == "SHOW SEMANTIC VIEWS IN SCHEMA db.analytics"
        rows = [{"name": "REV_SV", "database_name": "PROD", "schema_name": "FINANCE"}]
        assert self.p.parse_list_views(rows) == ["PROD.FINANCE.REV_SV"]

    def test_describe_parsing(self):
        rows = [
            {"object_kind": "TABLE", "object_name": "orders", "property": "BASE_TABLE", "property_value": "raw.orders"},
            {"object_kind": "METRIC", "object_name": "total_revenue", "property": "EXPRESSION", "property_value": "SUM(orders.amount)"},
            {"object_kind": "METRIC", "object_name": "total_revenue", "property": "COMMENT", "property_value": "Recognized revenue"},
            {"object_kind": "METRIC", "object_name": "order_count", "property": "EXPRESSION", "property_value": "COUNT(orders.id)"},
            {"object_kind": "DIMENSION", "object_name": "region", "property": "EXPRESSION", "property_value": "customers.region"},
        ]
        obj = self.p.parse_describe("PROD.FIN.REV_SV", rows)
        assert {m.name for m in obj.metrics} == {"total_revenue", "order_count"}
        rev = next(m for m in obj.metrics if m.name == "total_revenue")
        assert rev.expression == "SUM(orders.amount)"
        assert rev.description == "Recognized revenue"
        assert obj.dimensions == ["region"]

    def test_reference_query(self):
        sql = self.p.reference_query(
            "PROD.FIN.REV_SV", metrics=["total_revenue"], dimensions=["region", "month"]
        )
        assert sql == (
            "SELECT * FROM SEMANTIC_VIEW(PROD.FIN.REV_SV "
            "METRICS total_revenue DIMENSIONS region, month)"
        )

    def test_reference_query_no_dims(self):
        sql = self.p.reference_query("SV", metrics=["m"], dimensions=[])
        assert sql == "SELECT * FROM SEMANTIC_VIEW(SV METRICS m)"

    def test_invalid_identifiers_rejected(self):
        with pytest.raises(ValueError):
            self.p.reference_query("SV", metrics=["m; DROP TABLE x"], dimensions=[])
        with pytest.raises(ValueError):
            self.p.reference_query("SV--", metrics=["m"], dimensions=[])
        with pytest.raises(ValueError):
            self.p.describe_sql("a.b.c.d")

    def test_logical_table_qualified_names_accepted(self):
        sql = self.p.reference_query(
            "PROD.FIN.REV_SV", metrics=["orders.total_revenue"], dimensions=["customers.region"]
        )
        assert "METRICS orders.total_revenue" in sql
        assert "DIMENSIONS customers.region" in sql


class TestDatabricksProvider:
    p = DatabricksMetricProvider()

    def test_list_sql_scoped(self):
        sql = self.p.list_views_sql("main.gold")
        assert "table_catalog = 'main'" in sql and "table_schema = 'gold'" in sql

    def test_describe_detects_metric_view_and_parses_yaml(self):
        yaml_def = """version: 0.1
source: main.gold.orders
measures:
  - name: total_revenue
    expr: SUM(amount)
  - name: order_count
    expr: COUNT(1)
dimensions:
  - name: region
  - name: order_month
"""
        rows = [
            {"col_name": "Type", "data_type": "METRIC_VIEW", "comment": ""},
            {"col_name": "View Text", "data_type": yaml_def, "comment": ""},
        ]
        obj = self.p.parse_describe("main.gold.rev_mv", rows)
        assert obj is not None
        assert [m.name for m in obj.metrics] == ["total_revenue", "order_count"]
        assert obj.metrics[0].expression == "SUM(amount)"
        assert obj.dimensions == ["region", "order_month"]

    def test_regular_view_returns_none(self):
        rows = [{"col_name": "Type", "data_type": "VIEW", "comment": ""}]
        assert self.p.parse_describe("main.gold.plain_view", rows) is None

    def test_reference_query_measure_group_by(self):
        sql = self.p.reference_query(
            "main.gold.rev_mv", metrics=["total_revenue"], dimensions=["region"]
        )
        assert sql == (
            "SELECT `region`, MEASURE(`total_revenue`) AS `total_revenue` "
            "FROM main.gold.rev_mv GROUP BY `region`"
        )

    def test_provider_routing(self):
        assert provider_for_db_type("snowflake").kind == "snowflake_semantic_view"
        assert provider_for_db_type("databricks").kind == "databricks_metric_view"
        assert provider_for_db_type("postgres") is None


class TestConformance:
    def _run(self, ref, mod, tolerance=0.005):
        return compare_metric(
            metric="total_revenue",
            dimensions=["region"],
            reference_rows=ref,
            model_rows=mod,
            reference_metric_col="total_revenue",
            model_metric_col="revenue",
            reference_dim_cols=["region"],
            model_dim_cols=["region"],
            tolerance=tolerance,
        )

    def test_exact_match_passes(self):
        ref = [{"region": "EU", "total_revenue": 100.0}, {"region": "US", "total_revenue": 250.0}]
        mod = [{"region": "EU", "revenue": 100.0}, {"region": "US", "revenue": 250.0}]
        report = self._run(ref, mod)
        assert report.verdict == "pass"
        assert all(g.status == "match" for g in report.groups)

    def test_within_tolerance_passes(self):
        ref = [{"region": "EU", "total_revenue": 1000.0}]
        mod = [{"region": "EU", "revenue": 1004.0}]  # +0.4%
        assert self._run(ref, mod).verdict == "pass"

    def test_drift_fails_with_rel_diff(self):
        ref = [{"region": "EU", "total_revenue": 1000.0}]
        mod = [{"region": "EU", "revenue": 1042.0}]  # +4.2%
        report = self._run(ref, mod)
        assert report.verdict == "fail"
        g = report.groups[0]
        assert g.status == "drift"
        assert g.rel_diff == pytest.approx(0.042)
        assert report.summary["worst_rel_diff"] == pytest.approx(0.042)

    def test_missing_groups_flagged(self):
        ref = [{"region": "EU", "total_revenue": 1.0}, {"region": "APAC", "total_revenue": 2.0}]
        mod = [{"region": "EU", "revenue": 1.0}, {"region": "LATAM", "revenue": 3.0}]
        report = self._run(ref, mod)
        statuses = {tuple(g.key): g.status for g in report.groups}
        assert statuses[("apac",)] == "missing_in_model"
        assert statuses[("latam",)] == "missing_in_reference"
        assert report.verdict == "fail"

    def test_case_and_whitespace_insensitive_alignment(self):
        ref = [{"REGION": "EU ", "TOTAL_REVENUE": 5.0}]
        mod = [{"region": "eu", "revenue": 5.0}]
        report = self._run(ref, mod)
        assert report.verdict == "pass"

    def test_zero_reference_nonzero_model_is_drift(self):
        ref = [{"region": "EU", "total_revenue": 0.0}]
        mod = [{"region": "EU", "revenue": 5.0}]
        report = self._run(ref, mod)
        assert report.groups[0].rel_diff == math.inf
        assert report.verdict == "fail"

    def test_null_metric_non_numeric_warns(self):
        ref = [{"region": "EU", "total_revenue": None}]
        mod = [{"region": "EU", "revenue": 5.0}]
        assert self._run(ref, mod).verdict == "warn"

    def test_both_null_matches(self):
        ref = [{"region": "EU", "total_revenue": None}]
        mod = [{"region": "EU", "revenue": None}]
        assert self._run(ref, mod).verdict == "pass"

    def test_render_markdown(self):
        ref = [{"region": "EU", "total_revenue": 1000.0}]
        mod = [{"region": "EU", "revenue": 1042.0}]
        report = self._run(ref, mod)
        md = render_conformance_markdown(report, source_name="PROD.FIN.REV_SV", model_name="rev_mart")
        assert "❌" in md and "+4.20%" in md and "rev_mart" in md and "drift" in md

    def test_render_pass_markdown(self):
        ref = [{"region": "EU", "total_revenue": 10.0}]
        mod = [{"region": "EU", "revenue": 10.0}]
        md = render_conformance_markdown(self._run(ref, mod), source_name="sv", model_name="m")
        assert "All groups agree" in md


class TestConformanceHardening:
    def _run(self, ref, mod, tolerance=0.005):
        return compare_metric(
            metric="m", dimensions=["region"],
            reference_rows=ref, model_rows=mod,
            reference_metric_col="m", model_metric_col="m",
            reference_dim_cols=["region"], model_dim_cols=["region"],
            tolerance=tolerance,
        )

    def test_empty_results_warn_not_pass(self):
        report = self._run([], [])
        assert report.verdict == "warn"
        assert any("no rows" in n for n in report.notes)

    def test_duplicate_model_groups_fail(self):
        """Model not aggregated at grain must not silently overwrite."""
        ref = [{"region": "EU", "m": 10.0}]
        mod = [{"region": "EU", "m": 4.0}, {"region": "EU", "m": 6.0}]
        report = self._run(ref, mod)
        assert report.groups[0].status == "duplicate_in_model"
        assert report.verdict == "fail"

    def test_zero_tolerance_is_exact(self):
        ref = [{"region": "EU", "m": 100.0}]
        mod = [{"region": "EU", "m": 100.0000001}]
        assert self._run(ref, mod, tolerance=0.0).verdict == "fail"
        assert self._run(ref, mod, tolerance=0.005).verdict == "pass"

    def test_decimal_and_datetime_key_normalization(self):
        import datetime
        from decimal import Decimal

        ref = [{"region": Decimal("3"), "m": 5.0}]
        mod = [{"region": 3.0, "m": 5.0}]
        assert self._run(ref, mod).verdict == "pass"
        ref2 = [{"region": datetime.datetime(2026, 7, 1), "m": 1.0}]
        mod2 = [{"region": datetime.date(2026, 7, 1), "m": 1.0}]
        assert self._run(ref2, mod2).verdict == "pass"

    def test_nan_metric_is_non_numeric(self):
        ref = [{"region": "EU", "m": float("nan")}]
        mod = [{"region": "EU", "m": float("nan")}]
        assert self._run(ref, mod).verdict == "warn"

    def test_summary_json_safe_with_infinite_drift(self):
        import json

        ref = [{"region": "EU", "m": 0.0}]
        mod = [{"region": "EU", "m": 5.0}]
        report = self._run(ref, mod)
        payload = json.dumps(report.summary, allow_nan=False)  # must not raise
        assert report.summary["groups_with_infinite_drift"] == 1
        assert report.summary["worst_rel_diff"] is None
        assert "Infinity" not in payload

    def test_truncation_flagged(self):
        ref = [{"region": f"r{i}", "m": 1.0} for i in range(30)]
        mod = [{"region": f"r{i}", "m": 1.0} for i in range(30)]
        report = compare_metric(
            metric="m", dimensions=["region"],
            reference_rows=ref, model_rows=mod,
            reference_metric_col="m", model_metric_col="m",
            reference_dim_cols=["region"], model_dim_cols=["region"],
            tolerance=0.005, max_groups=10,
        )
        assert report.truncated and report.verdict == "warn"
        assert len(report.groups) == 10


class TestDatabricksYamlProperties:
    def test_extra_item_properties_do_not_truncate_section(self):
        p = DatabricksMetricProvider()
        yaml_def = """version: 0.1
source: main.gold.orders
measures:
  - name: total_revenue
    expr: SUM(amount)
    comment: recognized revenue only
    format: currency
  - name: order_count
    expr: COUNT(1)
dimensions:
  - name: region
    synonyms: [geo]
  - name: order_month
"""
        rows = [
            {"col_name": "Type", "data_type": "METRIC_VIEW", "comment": ""},
            {"col_name": "View Text", "data_type": yaml_def, "comment": ""},
        ]
        obj = p.parse_describe("main.gold.rev_mv", rows)
        assert [m.name for m in obj.metrics] == ["total_revenue", "order_count"]
        assert obj.dimensions == ["region", "order_month"]
