"""SignalPilot Data SDK — governed data access for notebooks and scripts."""
from __future__ import annotations

import os
from typing import Any

from signalpilot._sdk._artifacts import (
    apply_chart_theme as _apply_chart_theme,
    artifact_path as _artifact_path,
)
from signalpilot._sdk._checks import checks as checks
from signalpilot._sdk._client import GatewayClient, _is_local_url
from signalpilot._sdk._connection import Connection, DatasetRef
from signalpilot._sdk._runtime_publication import (
    PublishedResult,
    open_dataset as _open_dataset,
    publish_result as _publish_result,
)
from signalpilot._server.auth.session_token import load_session_jwt

_gw: GatewayClient | None = None


def init(
    gateway_url: str | None = None,
    api_key: str | None = None,
    session_token: str | None = None,
    session_token_file: str | os.PathLike[str] | None = None,
) -> None:
    """Initialize the SignalPilot Data SDK.

    Local:    sp.init()
    Cloud:    sp.init(api_key="sp_...")
    Sandbox:  sp.init(gateway_url=..., session_token_file=...)   # internal

    session_token_file points at a run-scoped credential the runtime rotates
    between chat turns. The client reads it per request, so a kernel kept
    alive across turns always presents the active run's token.

    Inside a chat run the house chart theme is applied here, so plain
    matplotlib and Plotly figures match the product without any styling.
    """
    from signalpilot._utils.localhost import fix_localhost_url
    global _gw
    url = fix_localhost_url(gateway_url or os.environ.get("SP_GATEWAY_URL") or "http://localhost:3300")
    token = session_token or api_key or load_session_jwt() or os.environ.get("SP_API_KEY")
    if not _is_local_url(url) and not token and not session_token_file:
        raise ValueError(
            "API key required for remote gateway. "
            "Pass api_key= or set SP_API_KEY env var."
        )
    _gw = GatewayClient(url, token, token_file=session_token_file)
    if os.getenv("SP_CHAT_SCRATCH_DIRECTORY") or os.getenv(
        "SP_CHAT_ARTIFACTS_DIRECTORY"
    ):
        _apply_chart_theme()


def connections() -> list[str]:
    """List available connection names."""
    _require_init()
    assert _gw is not None
    data = _gw.get("/api/connections")
    if isinstance(data, list):
        return [c["name"] if isinstance(c, dict) else c for c in data]
    return []


def connect(connection_name: str) -> Connection:
    """Get a Connection object for a named database connection."""
    _require_init()
    assert _gw is not None
    return Connection(connection_name, _gw)


def publish_result(
    dataframe: Any,
    *,
    name: str,
    source_result_ids: list[str],
    completeness: str,
    reconciliation: str | None = None,
) -> PublishedResult:
    """Publish a compact notebook-derived result without exposing its rows to the agent."""
    _require_init()
    assert _gw is not None
    return _publish_result(
        _gw,
        dataframe,
        name=name,
        source_result_ids=source_result_ids,
        completeness=completeness,
        reconciliation=reconciliation,
    )


def artifact_path(name: str) -> os.PathLike[str]:
    """Return the path for one artifact file and create its directory.

    Save a chart with `fig.savefig(sp.artifact_path("revenue.png"))`. The
    chat captures every file under the artifacts directory.
    """
    return _artifact_path(name)


def apply_chart_theme() -> None:
    """Apply the SignalPilot matplotlib rcParams and Plotly template."""
    _apply_chart_theme()


def open_dataset(dataset: DatasetRef) -> Any:
    """Open an opaque DatasetRef as a lazy Polars or DuckDB scan."""
    return _open_dataset(dataset)


def _require_init() -> None:
    if _gw is None:
        raise RuntimeError(
            "SDK not initialized. Call sp.init() first.\n"
            "  Local:  sp.init()\n"
            "  Cloud:  sp.init(api_key='sp_...')"
        )
