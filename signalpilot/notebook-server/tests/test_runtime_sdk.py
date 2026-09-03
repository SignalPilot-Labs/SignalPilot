from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from signalpilot._sdk._artifacts import (
    CHART_COLORS,
    apply_chart_theme,
    artifact_path,
    artifacts_directory,
)
from signalpilot._sdk._checks import checks
from signalpilot._sdk._client import GatewayClient
from signalpilot._sdk._connection import Connection, DatasetRef
from signalpilot._sdk._runtime_publication import open_dataset


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


def test_artifact_path_resolves_the_directory_and_creates_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("SP_CHAT_ARTIFACTS_DIRECTORY", raising=False)
    monkeypatch.delenv("SP_CHAT_SCRATCH_DIRECTORY", raising=False)
    monkeypatch.chdir(tmp_path)
    # Outside chat: a plain notebook writes to ./artifacts.
    assert artifacts_directory() == Path("artifacts")
    plain = artifact_path("chart.png")
    assert plain == Path("artifacts") / "chart.png"
    assert (tmp_path / "artifacts").is_dir()

    # Inside chat without the explicit variable: $SCRATCH/artifacts.
    scratch = tmp_path / "scratch"
    monkeypatch.setenv("SP_CHAT_SCRATCH_DIRECTORY", str(scratch))
    assert artifacts_directory() == scratch / "artifacts"

    # The explicit variable wins and nested names create their directory.
    explicit = tmp_path / "explicit"
    monkeypatch.setenv("SP_CHAT_ARTIFACTS_DIRECTORY", str(explicit))
    nested = artifact_path("charts/revenue_by_month.png")
    assert nested == explicit / "charts" / "revenue_by_month.png"
    assert nested.parent.is_dir()
    assert not nested.exists()


@pytest.mark.parametrize(
    "name",
    ["", "   ", "/abs.png", "../up.png", "a/../b.png", ".hidden.png", "./x.png", "a/./b"],
)
def test_artifact_path_rejects_unsafe_names(
    name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SP_CHAT_ARTIFACTS_DIRECTORY", str(tmp_path))
    with pytest.raises(ValueError):
        artifact_path(name)


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


def test_chart_theme_sets_the_house_rc_params_and_plotly_template():
    import matplotlib as mpl

    with mpl.rc_context():
        apply_chart_theme()
        assert mpl.rcParams["figure.facecolor"] == "#141416"
        assert mpl.rcParams["savefig.facecolor"] == "#141416"
        assert mpl.rcParams["axes.facecolor"] == "#141416"
        assert mpl.rcParams["text.color"] == "#EDEDED"
        assert mpl.rcParams["axes.labelcolor"] == "#EDEDED"
        assert mpl.rcParams["xtick.color"] == "#EDEDED"
        assert mpl.rcParams["ytick.color"] == "#EDEDED"
        assert mpl.rcParams["axes.edgecolor"] == "#55555C"
        assert mpl.rcParams["grid.color"] == "#333338"
        assert mpl.rcParams["axes.spines.top"] is False
        assert mpl.rcParams["axes.spines.right"] is False
        assert list(mpl.rcParams["figure.figsize"]) == [10, 5.6]
        assert mpl.rcParams["figure.dpi"] == 200
        assert mpl.rcParams["savefig.dpi"] == 200
        assert mpl.rcParams["savefig.bbox"] == "tight"
        assert mpl.rcParams["savefig.pad_inches"] == 0.3
        assert mpl.rcParams["font.sans-serif"][0] == "DM Sans"
        assert mpl.rcParams["legend.frameon"] is False
        assert mpl.rcParams["axes.prop_cycle"].by_key()["color"] == list(
            CHART_COLORS
        )
        assert list(CHART_COLORS) == [
            "#56B4E9",
            "#E69F00",
            "#009E73",
            "#F0E442",
            "#0072B2",
            "#D55E00",
            "#CC79A7",
            "#B3B3B3",
        ]

    plotly_io = pytest.importorskip("plotly.io")
    assert plotly_io.templates.default == "signalpilot"
    layout = plotly_io.templates["signalpilot"].layout
    assert layout.paper_bgcolor == "#141416"
    assert list(layout.colorway) == list(CHART_COLORS)


def test_chart_theme_survives_a_missing_plotly(monkeypatch: pytest.MonkeyPatch):
    import matplotlib as mpl

    monkeypatch.setitem(sys.modules, "plotly", None)
    monkeypatch.setitem(sys.modules, "plotly.io", None)
    monkeypatch.setitem(sys.modules, "plotly.graph_objects", None)
    with mpl.rc_context():
        apply_chart_theme()
        assert mpl.rcParams["figure.facecolor"] == "#141416"


def test_init_applies_the_theme_only_inside_a_chat_run(
    monkeypatch: pytest.MonkeyPatch,
):
    import matplotlib as mpl

    from signalpilot import _sdk

    monkeypatch.setattr(_sdk, "load_session_jwt", lambda: None)
    monkeypatch.delenv("SP_CHAT_SCRATCH_DIRECTORY", raising=False)
    monkeypatch.delenv("SP_CHAT_ARTIFACTS_DIRECTORY", raising=False)
    with mpl.rc_context():
        mpl.rcParams["figure.facecolor"] = "white"
        _sdk.init(gateway_url="http://localhost:3300")
        assert mpl.rcParams["figure.facecolor"] == "white"

        monkeypatch.setenv("SP_CHAT_ARTIFACTS_DIRECTORY", "/tmp/run/artifacts")
        _sdk.init(gateway_url="http://localhost:3300")
        assert mpl.rcParams["figure.facecolor"] == "#141416"


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
