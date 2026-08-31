from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from signalpilot._sdk._checks import checks
from signalpilot._sdk._client import GatewayClient
from signalpilot._sdk._connection import Connection, DatasetRef
from signalpilot._sdk._runtime_publication import (
    _scratch_path,
    apply_runtime_chart_theme,
    open_dataset,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_notebook_queries_hide_internal_plan_ids_and_execution_need():
    class RecordingClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def post(self, path: str, body: dict, **_kwargs: object):
            self.calls.append((path, body))
            if path == "/api/query":
                return {"rows": [{"value": 7}], "result_id": "result-a"}
            if path == "/api/query/datasets":
                return {
                    "dataset_id": "dataset-a",
                    "schema": [],
                    "row_count": 1,
                    "byte_size": 8,
                    "completeness": "complete",
                    "expires_at": "2026-09-01T00:00:00Z",
                }
            raise AssertionError(path)

    client = RecordingClient()
    connection = Connection("production", client)  # type: ignore[arg-type]

    assert connection.query_result("select 7")["rows"] == [{"value": 7}]
    assert connection.query_dataset("select 7").id == "dataset-a"
    assert client.calls == [
        (
            "/api/query",
            {"connection_name": "production", "sql": "select 7", "row_limit": 100_000},
        ),
        (
            "/api/query/datasets",
            {"connection_name": "production", "sql": "select 7"},
        ),
    ]


def test_dataset_ref_representation_never_exposes_gateway_token():
    client = GatewayClient("https://gateway.example", "secret-run-token")
    dataset = DatasetRef(
        id="dataset-a",
        schema=({"name": "amount", "logical_type": "decimal"},),
        row_count=1_000_000,
        byte_size=123_456,
        completeness="complete",
        expires_at="2026-08-05T00:00:00Z",
        _client=client,
    )

    assert "secret-run-token" not in repr(client)
    assert "secret-run-token" not in repr(dataset)
    assert "_client" not in repr(dataset)


def test_open_dataset_uses_a_short_lived_lazy_remote_scan(monkeypatch: pytest.MonkeyPatch):
    class AccessClient:
        def post(self, path: str):
            assert path == "/api/query/datasets/dataset-a/access"
            return {"url": "https://objects.example/private.parquet?signature=temporary"}

    calls: list[str] = []
    monkeypatch.setitem(
        sys.modules,
        "polars",
        SimpleNamespace(scan_parquet=lambda url: calls.append(url) or "lazy-frame"),
    )
    dataset = DatasetRef(
        id="dataset-a",
        schema=(),
        row_count=1_000_000,
        byte_size=10_000_000,
        completeness="complete",
        expires_at="2026-08-05T00:00:00Z",
        _client=AccessClient(),  # type: ignore[arg-type]
    )

    assert open_dataset(dataset) == "lazy-frame"
    assert calls == ["https://objects.example/private.parquet?signature=temporary"]


def test_runtime_artifact_path_rejects_traversal_and_symlinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    artifact = scratch / "table.csv"
    artifact.write_text("value\n1\n", encoding="utf-8")
    outside = tmp_path / "outside.csv"
    outside.write_text("value\n2\n", encoding="utf-8")
    link = scratch / "linked.csv"
    link.symlink_to(artifact)
    monkeypatch.setenv("SP_CHAT_SCRATCH_DIRECTORY", str(scratch))

    assert _scratch_path("table.csv") == artifact
    with pytest.raises(ValueError, match="inside the run scratch"):
        _scratch_path(outside)
    with pytest.raises(ValueError, match="symlink"):
        _scratch_path(link)


def test_runtime_checks_return_only_compact_quality_metadata():
    rows = [
        {"id": 1, "occurred_at": "2026-08-03T12:00:00Z", "value": 10},
        {"id": 1, "occurred_at": None, "value": None},
    ]

    assert checks.nulls(rows) == {
        "row_count": 2,
        "null_counts": {"id": 0, "occurred_at": 1, "value": 1},
        "passed": False,
    }
    assert checks.duplicates(rows, columns=["id"])["duplicate_count"] == 1
    assert checks.date_range(rows, column="occurred_at")["maximum"] == "2026-08-03T12:00:00+00:00"
    assert checks.freshness(
        rows,
        column="occurred_at",
        maximum_age_seconds=86_400,
        now=datetime(2026, 8, 4, 12, tzinfo=UTC),
    )["passed"] is True
    assert checks.reconciliation(actual=100.01, expected=100, tolerance=0.02)["passed"] is True


def test_runtime_chart_theme_uses_signalpilot_defaults():
    import matplotlib as mpl

    with mpl.rc_context():
        apply_runtime_chart_theme()
        assert mpl.rcParams["figure.facecolor"] == "#141416"
        assert mpl.rcParams["axes.edgecolor"] == "#55555C"
        assert mpl.rcParams["axes.prop_cycle"].by_key()["color"] == [
            "#56B4E9",
            "#E69F00",
            "#009E73",
            "#F0E442",
            "#0072B2",
            "#D55E00",
            "#CC79A7",
            "#B3B3B3",
        ]


def test_gateway_client_reads_rotated_token_file_per_request(tmp_path: Path):
    """A kept-alive kernel must present the ACTIVE run's token.

    Adoption rotates the token file between chat turns. The client reads the
    file per request and keeps the last token when the file is removed at
    run end.
    """
    token_file = tmp_path / ".gateway-token"
    token_file.write_text("token-run-1", encoding="utf-8")
    client = GatewayClient("https://gw.example", token_file=token_file)
    assert client._headers()["Authorization"] == "Bearer token-run-1"

    import os as _os

    token_file.write_text("token-run-2", encoding="utf-8")
    _os.utime(token_file, (1_700_000_000, 1_700_000_000))
    assert client._headers()["Authorization"] == "Bearer token-run-2"

    token_file.unlink()
    assert client._headers()["Authorization"] == "Bearer token-run-2"
