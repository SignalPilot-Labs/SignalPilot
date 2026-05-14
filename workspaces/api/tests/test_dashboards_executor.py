"""Tests for DbtProxyExecutor using fakes for psycopg and ProxyTokenClient."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from workspaces_api.agent.proxy_token_client import ProxyTokenLease
from workspaces_api.config import Settings
from workspaces_api.dashboards.errors import ChartExecutionFailed, ChartExecutionTimeout
from workspaces_api.dashboards.executor import DbtProxyExecutor
from workspaces_api.errors import ProxyTokenMintFailed

_SETTINGS = Settings.model_validate({
    "SP_DEPLOYMENT_MODE": "local",
    "CLAUDE_CODE_OAUTH_TOKEN": "tok",
    "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
})

_CONNECTOR = "my_connector"
_SQL = "SELECT id, name FROM users"
_PARAMS: dict[str, Any] = {}


# ── Fake token client ──────────────────────────────────────────────────────────

@dataclass
class FakeTokenClient:
    mint_calls: list[tuple[uuid.UUID, str, int]] = field(default_factory=list)
    revoke_calls: list[uuid.UUID] = field(default_factory=list)
    mint_result: ProxyTokenLease = field(default_factory=lambda: ProxyTokenLease(
        token="fake-token-hex",
        host_port=15432,
        expires_at=datetime(2026, 5, 1, 13, 0, tzinfo=timezone.utc),
    ))
    raise_on_mint: Exception | None = None

    async def mint(
        self, run_id: uuid.UUID, connector_name: str, ttl_seconds: int
    ) -> ProxyTokenLease:
        self.mint_calls.append((run_id, connector_name, ttl_seconds))
        if self.raise_on_mint is not None:
            raise self.raise_on_mint
        return self.mint_result

    async def revoke(self, run_id: uuid.UUID) -> None:
        self.revoke_calls.append(run_id)


# ── Fake psycopg cursor ────────────────────────────────────────────────────────

@dataclass
class FakeCursor:
    _rows: list[tuple] = field(default_factory=list)
    description: list[Any] = field(default_factory=list)

    async def execute(self, sql: str, params: Any) -> None:
        pass

    async def __aenter__(self) -> "FakeCursor":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    def __aiter__(self) -> "FakeCursor":
        self._iter = iter(self._rows)
        return self

    async def __anext__(self) -> tuple:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


@dataclass
class FakeConn:
    cursor_obj: FakeCursor = field(default_factory=FakeCursor)

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    async def __aenter__(self) -> "FakeConn":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


def _make_connect_factory(
    conn: FakeConn,
) -> Any:
    """Returns a factory that accepts (conninfo, autocommit=...) and returns FakeConn."""
    async def _factory(conninfo: str, autocommit: bool = False) -> FakeConn:
        return conn

    return _factory


def _make_chart(connector_name: str = _CONNECTOR) -> Any:
    """Create a minimal Chart-like object."""
    from unittest.mock import MagicMock
    chart = MagicMock()
    chart.id = uuid.uuid4()
    chart.workspace_id = "ws-test"
    return chart


def _make_query(sql: str = _SQL, connector_name: str = _CONNECTOR) -> Any:
    """Create a minimal ChartQuery-like object."""
    from unittest.mock import MagicMock
    q = MagicMock()
    q.id = uuid.uuid4()
    q.connector_name = connector_name
    q.sql = sql
    q.params = {}
    q.refresh_interval_seconds = 3600
    return q


# ── Session fake ──────────────────────────────────────────────────────────────

class FakeSession:
    def __init__(self) -> None:
        self._added: list[Any] = []
        self._committed = False
        self._flushed = False

    def add(self, obj: Any) -> None:
        self._added.append(obj)

    async def flush(self) -> None:
        self._flushed = True

    async def commit(self) -> None:
        self._committed = True

    async def refresh(self, obj: Any) -> None:
        pass

    async def get(self, model: Any, pk: Any) -> Any:
        return None

    async def delete(self, obj: Any) -> None:
        pass

    async def execute(self, stmt: Any) -> Any:
        result = AsyncMock()
        result.scalar_one_or_none.return_value = None
        return result


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestDbtProxyExecutor:
    @pytest.mark.asyncio
    async def test_happy_path_mint_connect_capture_revoke(self) -> None:
        from unittest.mock import MagicMock
        col = MagicMock()
        col.name = "id"
        col.type_code = 23  # int4

        cursor = FakeCursor(
            description=[col],
            _rows=[(1,), (2,), (3,)],
        )
        conn = FakeConn(cursor_obj=cursor)
        token_client = FakeTokenClient()
        connect_factory = _make_connect_factory(conn)

        executor = DbtProxyExecutor(
            settings=_SETTINGS,
            token_client=token_client,
            connect_factory=connect_factory,
        )
        session = FakeSession()
        chart = _make_chart()
        query = _make_query()

        result = await executor.execute(chart, query, {}, session)

        assert result.columns == [{"name": "id", "type_hint": "int"}]
        assert result.rows == [[1], [2], [3]]
        assert result.truncated is False
        assert len(token_client.mint_calls) == 1
        assert len(token_client.revoke_calls) == 1
        # revoke used the same run_id as mint
        assert token_client.revoke_calls[0] == token_client.mint_calls[0][0]
        assert session._committed is True

    @pytest.mark.asyncio
    async def test_conninfo_contains_host_port_user_options(self) -> None:
        """Verify _build_conninfo shapes match gateway expectations."""
        from unittest.mock import MagicMock
        col = MagicMock()
        col.name = "x"
        col.type_code = 25

        captured_conninfos: list[str] = []

        async def _factory(conninfo: str, autocommit: bool = False) -> FakeConn:
            captured_conninfos.append(conninfo)
            cursor = FakeCursor(description=[col], _rows=[("val",)])
            return FakeConn(cursor_obj=cursor)

        token_client = FakeTokenClient()
        executor = DbtProxyExecutor(
            settings=_SETTINGS,
            token_client=token_client,
            connect_factory=_factory,
        )
        await executor.execute(_make_chart(), _make_query(), {}, FakeSession())

        assert len(captured_conninfos) == 1
        conninfo = captured_conninfos[0]
        assert "host=" in conninfo or "127.0.0.1" in conninfo
        assert "15432" in conninfo
        assert "run-" in conninfo
        assert "statement_timeout" in conninfo

    @pytest.mark.asyncio
    async def test_mint_failed_propagates_no_connect_no_revoke(self) -> None:
        token_client = FakeTokenClient(
            raise_on_mint=ProxyTokenMintFailed("auth", correlation_id="abc123")
        )
        connect_calls = []

        async def _factory(conninfo: str, autocommit: bool = False) -> FakeConn:
            connect_calls.append(conninfo)
            return FakeConn()

        executor = DbtProxyExecutor(
            settings=_SETTINGS,
            token_client=token_client,
            connect_factory=_factory,
        )
        with pytest.raises(ProxyTokenMintFailed):
            await executor.execute(_make_chart(), _make_query(), {}, FakeSession())

        assert len(connect_calls) == 0
        assert len(token_client.revoke_calls) == 0

    @pytest.mark.asyncio
    async def test_psycopg_error_raises_chart_execution_failed_and_revokes(self) -> None:
        import psycopg

        async def _factory(conninfo: str, autocommit: bool = False) -> FakeConn:
            raise psycopg.OperationalError("connection refused")

        token_client = FakeTokenClient()
        executor = DbtProxyExecutor(
            settings=_SETTINGS,
            token_client=token_client,
            connect_factory=_factory,
        )
        with pytest.raises(ChartExecutionFailed) as exc_info:
            await executor.execute(_make_chart(), _make_query(), {}, FakeSession())

        assert exc_info.value.correlation_id is not None
        assert len(token_client.revoke_calls) == 1

    @pytest.mark.asyncio
    async def test_timeout_raises_chart_execution_timeout_and_revokes(self) -> None:
        async def _slow_factory(conninfo: str, autocommit: bool = False) -> FakeConn:
            await asyncio.sleep(100)  # will be cancelled by timeout
            return FakeConn()  # unreachable

        token_client = FakeTokenClient()
        settings = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "CLAUDE_CODE_OAUTH_TOKEN": "tok",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "SP_CHART_TOTAL_DEADLINE_SECONDS": "1",
            "SP_CHART_CONNECT_TIMEOUT_SECONDS": "1",
        })
        executor = DbtProxyExecutor(
            settings=settings,
            token_client=token_client,
            connect_factory=_slow_factory,
        )
        with pytest.raises(ChartExecutionTimeout) as exc_info:
            await executor.execute(_make_chart(), _make_query(), {}, FakeSession())

        assert exc_info.value.correlation_id is not None
        assert len(token_client.revoke_calls) == 1

    @pytest.mark.asyncio
    async def test_truncated_propagates_into_result(self) -> None:
        from unittest.mock import MagicMock

        col = MagicMock()
        col.name = "val"
        col.type_code = 25  # text

        # 1001 rows will exceed default max_rows=10000? No, use a small cap via settings
        settings = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "CLAUDE_CODE_OAUTH_TOKEN": "tok",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "SP_CHART_MAX_ROWS": "5",
        })
        cursor = FakeCursor(
            description=[col],
            _rows=[(f"row{i}",) for i in range(10)],
        )
        conn = FakeConn(cursor_obj=cursor)

        token_client = FakeTokenClient()
        executor = DbtProxyExecutor(
            settings=settings,
            token_client=token_client,
            connect_factory=_make_connect_factory(conn),
        )
        result = await executor.execute(_make_chart(), _make_query(), {}, FakeSession())

        assert result.truncated is True
        assert len(result.rows) == 5

    @pytest.mark.asyncio
    async def test_repr_of_lease_does_not_leak_token(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Smoke check: lease.token must not appear in any log record."""
        from unittest.mock import MagicMock

        col = MagicMock()
        col.name = "x"
        col.type_code = 25

        secret_token = "super-secret-proxy-token-value"
        lease = ProxyTokenLease(
            token=secret_token,
            host_port=15432,
            expires_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )

        class TokenClient(FakeTokenClient):
            async def mint(
                self, run_id: uuid.UUID, connector_name: str, ttl_seconds: int
            ) -> ProxyTokenLease:
                self.mint_calls.append((run_id, connector_name, ttl_seconds))
                return lease

        cursor = FakeCursor(description=[col], _rows=[("v",)])
        conn = FakeConn(cursor_obj=cursor)
        token_client = TokenClient()

        executor = DbtProxyExecutor(
            settings=_SETTINGS,
            token_client=token_client,
            connect_factory=_make_connect_factory(conn),
        )
        with caplog.at_level(logging.DEBUG, logger="workspaces_api"):
            await executor.execute(_make_chart(), _make_query(), {}, FakeSession())

        for record in caplog.records:
            assert secret_token not in record.getMessage(), (
                f"Token leaked in log: {record.getMessage()}"
            )
        # Also check the repr itself
        assert secret_token not in repr(lease)
