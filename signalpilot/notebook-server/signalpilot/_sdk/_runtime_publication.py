"""Opaque runtime result and DatasetRef SDK helpers."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from signalpilot._sdk._client import GatewayClient
from signalpilot._sdk._connection import DatasetRef

MAX_RUNTIME_ROWS = 100_000
MAX_RUNTIME_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class PublishedResult:
    id: str
    name: str
    row_count: int
    byte_size: int
    completeness: str


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
