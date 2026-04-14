"""Tests for the connector registry."""

import pytest

from signalpilot.gateway.gateway.connectors.registry import get_connector, get_sqlite_connector
from signalpilot.gateway.gateway.connectors.base import BaseConnector
from signalpilot.gateway.gateway.connectors.postgres import PostgresConnector
from signalpilot.gateway.gateway.connectors.duckdb import DuckDBConnector


class TestConnectorRegistry:
    """Tests for get_connector() routing."""

    def test_postgres_returns_postgres_connector(self):
        conn = get_connector("postgres")
        assert isinstance(conn, PostgresConnector)
        assert isinstance(conn, BaseConnector)

    def test_duckdb_returns_duckdb_connector(self):
        conn = get_connector("duckdb")
        assert isinstance(conn, DuckDBConnector)
        assert isinstance(conn, BaseConnector)

    def test_unsupported_type_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            get_connector("mongodb")

    def test_unsupported_type_lists_supported(self):
        with pytest.raises(ValueError, match="postgres"):
            get_connector("redis")

    def test_each_call_returns_new_instance(self):
        c1 = get_connector("postgres")
        c2 = get_connector("postgres")
        assert c1 is not c2

    def test_sqlite_connector(self):
        conn = get_sqlite_connector()
        assert isinstance(conn, BaseConnector)
