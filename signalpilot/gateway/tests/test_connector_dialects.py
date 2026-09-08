"""Connector dialect contract: every registered connector binds parameters natively."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from gateway.connectors.dialects import ConnectorDialectError
from gateway.connectors.drivers.bigquery import BigQueryConnector
from gateway.connectors.drivers.clickhouse import ClickHouseConnector
from gateway.connectors.drivers.trino import TrinoConnector
from gateway.connectors.registry import (
    get_connector_dialect,
    get_connector_registration,
    registered_connector_types,
)
from gateway.governance.bindings import BoundQuery, BoundQueryError, ParameterStyle
from gateway.models import DBType


def test_gateway_registry_has_a_dialect_for_every_connector() -> None:
    expected = {db_type.value for db_type in DBType}
    assert set(registered_connector_types()) == expected
    assert {db_type: get_connector_registration(db_type).dialect.db_type for db_type in registered_connector_types()} == {
        db_type: db_type for db_type in registered_connector_types()
    }
    assert get_connector_dialect(DBType.postgres).parameter_style == ParameterStyle.NUMERIC_DOLLAR
    assert get_connector_dialect("xata").sqlglot_name == "postgres"


def test_unknown_connector_dialect_fails_closed() -> None:
    with pytest.raises(ValueError, match="Unsupported database type"):
        get_connector_dialect("future-db")


def test_quote_identifier_escapes_per_dialect() -> None:
    assert get_connector_dialect("mssql").quote_identifier("a]b") == "[a]]b]"
    assert get_connector_dialect("postgres").quote_identifier('a"b') == '"a""b"'
    assert get_connector_dialect("mysql").quote_identifier("a`b") == "`a``b`"
    with pytest.raises(ConnectorDialectError):
        get_connector_dialect("postgres").quote_identifier("")


def test_bound_query_rejects_missing_duplicate_reordered_and_extra_tokens() -> None:
    invalid = (
        ("SELECT :sp_dashboard_0", (1, 2)),
        ("SELECT :sp_dashboard_0, :sp_dashboard_0", (1, 2)),
        ("SELECT :sp_dashboard_1, :sp_dashboard_0", (1, 2)),
        ("SELECT :sp_dashboard_0, :sp_dashboard_1", (1,)),
    )
    for sql, parameters in invalid:
        with pytest.raises(BoundQueryError):
            BoundQuery(sql, parameters, "postgres", ParameterStyle.NUMERIC_DOLLAR)


def test_bound_query_ignores_placeholder_like_text_in_literals_and_comments() -> None:
    query = BoundQuery(
        "SELECT ':sp_dashboard_0 %s ? $1' AS note -- :sp_dashboard_9\nWHERE id = :sp_dashboard_0",
        (7,),
        "postgres",
        ParameterStyle.NUMERIC_DOLLAR,
    )
    assert query.render().sql == ("SELECT ':sp_dashboard_0 %s ? $1' AS note -- :sp_dashboard_9\nWHERE id = $1")


def test_every_registered_dialect_renders_native_bindings_without_values_in_sql() -> None:
    values = ("O'Reilly", 17)
    for db_type in registered_connector_types():
        dialect = get_connector_dialect(db_type)
        query = BoundQuery(
            "SELECT :sp_dashboard_0, :sp_dashboard_1",
            values,
            db_type,
            dialect.parameter_style,
        )
        rendered = query.render()
        assert values[0] not in rendered.sql
        if dialect.parameter_style == ParameterStyle.NAMED_PYFORMAT:
            assert rendered.parameters == {"sp_dashboard_0": values[0], "sp_dashboard_1": values[1]}
        else:
            assert rendered.parameters == list(values)


@pytest.mark.asyncio
async def test_bigquery_driver_creates_typed_positional_parameters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeQueryJobConfig:
        query_parameters: list[object]

    class FakeScalarQueryParameter:
        def __init__(self, name, type_name, value):
            self.name = name
            self.type_name = type_name
            self.value = value

    class FakeJob:
        total_bytes_processed = 0
        total_bytes_billed = 0
        cache_hit = False
        slot_millis = 0
        job_id = "job-1"

        def result(self, *, timeout=None):
            return [{"value": 1}]

    class FakeClient:
        def query(self, sql, *, job_config, timeout=None):
            captured.update(sql=sql, config=job_config, timeout=timeout)
            return FakeJob()

    import gateway.connectors.drivers.bigquery as bigquery_driver

    monkeypatch.setattr(
        bigquery_driver,
        "bigquery",
        SimpleNamespace(
            QueryJobConfig=FakeQueryJobConfig,
            ScalarQueryParameter=FakeScalarQueryParameter,
        ),
        raising=False,
    )
    connector = BigQueryConnector()
    connector._client = FakeClient()
    values = [True, 7, Decimal("2.50"), datetime(2026, 1, 1, tzinfo=UTC)]
    assert await connector._execute_impl("SELECT ?, ?, ?, ?", values, timeout=9) == [{"value": 1}]
    parameters = captured["config"].query_parameters
    assert [(item.name, item.type_name, item.value) for item in parameters] == [
        (None, "BOOL", values[0]),
        (None, "INT64", values[1]),
        (None, "NUMERIC", values[2]),
        (None, "TIMESTAMP", values[3]),
    ]


@pytest.mark.asyncio
async def test_trino_driver_does_not_drop_qmark_parameters() -> None:
    calls: list[tuple] = []

    class FakeCursor:
        description = [("value",)]

        def execute(self, *args):
            calls.append(args)

        def fetchall(self):
            return [(1,)]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    connector = TrinoConnector()
    connector._conn = FakeConnection()
    assert await connector._execute_impl("SELECT ?", [7]) == [{"value": 1}]
    assert calls == [("SELECT ?", [7])]


def test_clickhouse_driver_passes_named_parameters_to_native_client() -> None:
    calls: list[tuple] = []

    class FakeClient:
        def execute(self, *args, **kwargs):
            calls.append((args, kwargs))
            return [], [("value",)]

    connector = ClickHouseConnector()
    connector._client = FakeClient()
    parameters = {"sp_dashboard_0": "North"}
    connector._raw_execute("SELECT %(sp_dashboard_0)s", parameters)
    assert calls == [
        (
            ("SELECT %(sp_dashboard_0)s", parameters),
            {"with_column_types": True},
        )
    ]
