"""Opaque runtime result, artifact, and DatasetRef SDK helpers."""

from __future__ import annotations

import base64
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from signalpilot._sdk._client import GatewayClient
from signalpilot._sdk._connection import DatasetRef

MAX_RUNTIME_ROWS = 100_000
MAX_RUNTIME_BYTES = 10 * 1024 * 1024
_EXTENSIONS = {
    "table": {".csv"},
    "chart": {".png"},
    "report": {".html", ".htm"},
}
_CHART_COLORS = (
    "#56B4E9",
    "#E69F00",
    "#009E73",
    "#F0E442",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
    "#B3B3B3",
)


@dataclass(frozen=True)
class PublishedResult:
    id: str
    name: str
    row_count: int
    byte_size: int
    completeness: str


@dataclass(frozen=True)
class PublishedArtifact:
    id: str
    filename: str
    kind: str
    byte_size: int


def apply_runtime_chart_theme() -> None:
    """Install the canonical chat theme as the runtime's plotting default."""
    import matplotlib as mpl

    mpl.rcParams.update(
        {
            "figure.facecolor": "#141416",
            "axes.facecolor": "#141416",
            "savefig.facecolor": "#141416",
            "text.color": "#EDEDED",
            "axes.labelcolor": "#EDEDED",
            "axes.edgecolor": "#55555C",
            "xtick.color": "#EDEDED",
            "ytick.color": "#EDEDED",
            "grid.color": "#333338",
            "axes.grid": True,
            "axes.prop_cycle": mpl.cycler(color=_CHART_COLORS),
        }
    )


def _records(dataframe: Any) -> list[dict[str, Any]]:
    if hasattr(dataframe, "to_dicts"):
        rows = dataframe.to_dicts()
    elif hasattr(dataframe, "to_dict"):
        try:
            rows = dataframe.to_dict(orient="records")
        except TypeError:
            rows = dataframe.to_dicts()
    elif isinstance(dataframe, list):
        rows = dataframe
    else:
        raise TypeError("publish_result expects a pandas or Polars DataFrame")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise TypeError("publish_result requires record-shaped rows")
    if len(rows) > MAX_RUNTIME_ROWS:
        raise ValueError("Derived result exceeds 100,000 rows; aggregate it before publication")
    return rows


def _notebook_code_hash() -> str:
    raw = os.getenv("SP_CHAT_NOTEBOOK_PATH", "").strip()
    if not raw:
        raise RuntimeError("Runtime notebook identity is unavailable")
    path = Path(raw).resolve()
    if not path.is_file():
        raise RuntimeError("Runtime notebook source is unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def publish_result(
    client: GatewayClient,
    dataframe: Any,
    *,
    name: str,
    source_result_ids: list[str],
    completeness: str,
    reconciliation: str | None = None,
) -> PublishedResult:
    if completeness not in {"complete", "truncated", "unknown"}:
        raise ValueError("completeness must be complete, truncated, or unknown")
    if not source_result_ids:
        raise ValueError("At least one source_result_id is required")
    rows = _records(dataframe)
    response = client.post(
        "/api/query/results/publish",
        {
            "name": name,
            "rows": rows,
            "source_result_ids": source_result_ids,
            "completeness": completeness,
            "reconciliation": reconciliation,
            "code_hash": _notebook_code_hash(),
        },
        timeout=300,
        headers={"X-SP-Query-Path": "sdk"},
    )
    return PublishedResult(
        id=str(response["result_id"]),
        name=str(response["name"]),
        row_count=int(response["row_count"]),
        byte_size=int(response["byte_size"]),
        completeness=str(response["completeness"]),
    )


def _scratch_path(path: str | os.PathLike[str]) -> Path:
    root_raw = os.getenv("SP_CHAT_SCRATCH_DIRECTORY", "").strip()
    if not root_raw:
        raise RuntimeError("Runtime scratch directory is unavailable")
    root = Path(root_raw).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    unresolved = candidate.absolute()
    if any(part.is_symlink() for part in (unresolved, *unresolved.parents) if part.exists()):
        raise ValueError("Artifact path must not contain symlinks")
    candidate = unresolved.resolve(strict=True)
    if candidate != root and root not in candidate.parents:
        raise ValueError("Artifact path must stay inside the run scratch directory")
    info = candidate.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError("Artifact path must be a regular, non-symlink file")
    return candidate


def publish_artifact(
    client: GatewayClient,
    path: str | os.PathLike[str],
    *,
    kind: str,
    result_id: str,
    assumptions: list[str] | None = None,
    exclusions: list[str] | None = None,
    caveats: list[str] | None = None,
) -> PublishedArtifact:
    if kind not in _EXTENSIONS:
        raise ValueError("kind must be table, chart, or report")
    file_path = _scratch_path(path)
    if file_path.suffix.lower() not in _EXTENSIONS[kind]:
        raise ValueError(f"Unsupported {kind} artifact extension")
    data = file_path.read_bytes()
    if not data or len(data) > MAX_RUNTIME_BYTES:
        raise ValueError("Artifact must be non-empty and no larger than 10 MiB")
    if kind == "chart" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Chart artifact content does not match PNG")
    if kind == "report" and b"<" not in data[:1024]:
        raise ValueError("Report artifact content does not match HTML")
    response = client.post(
        "/api/chat/runtime-artifacts",
        {
            "filename": file_path.name,
            "kind": kind,
            "result_id": result_id,
            "content_base64": base64.b64encode(data).decode("ascii"),
            "assumptions": assumptions or [],
            "exclusions": exclusions or [],
            "caveats": caveats or [],
            "code_hash": _notebook_code_hash(),
        },
        timeout=300,
    )
    return PublishedArtifact(
        id=str(response["artifact_id"]),
        filename=str(response["filename"]),
        kind=str(response["kind"]),
        byte_size=int(response["byte_size"]),
    )


def open_dataset(dataset: DatasetRef) -> Any:
    """Open a five-minute object-scoped URL as a lazy remote scan."""
    access = dataset._client.post(f"/api/query/datasets/{dataset.id}/access")
    url = str(access.get("url") or "") if isinstance(access, dict) else ""
    if not url:
        raise RuntimeError("DatasetRef access is unavailable")
    try:
        import polars as pl

        return pl.scan_parquet(url)
    except ImportError:
        import duckdb

        return duckdb.connect().from_parquet(url)
