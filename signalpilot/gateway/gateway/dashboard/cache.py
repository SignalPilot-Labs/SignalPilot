"""Stable identities for exact dashboard query receipts."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonical_scalar(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical_scalar(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical_scalar(item) for item in value]
    return value


def dashboard_query_cache_key(
    *,
    version_id: str,
    chart: Any,
    tile_uuid: str,
    requested_filters: list[Any],
    drill_path: list[Any],
    dashboard_filters: Any,
) -> str:
    """Bind a receipt to the immutable definition and exact visible controls."""

    def normalized_filter(item: Any) -> dict[str, Any]:
        payload = _canonical_scalar(item.model_dump(mode="json", exclude_none=True))
        if payload.get("operator") == "equals" and isinstance(payload.get("values"), list):
            payload["values"] = sorted(payload["values"], key=lambda value: json.dumps(value, sort_keys=True))
        return payload

    normalized_filters = sorted(
        (normalized_filter(item) for item in requested_filters),
        key=lambda item: (str(item.get("id")), json.dumps(item, sort_keys=True)),
    )
    payload = {
        "version_id": version_id,
        "chart_id": chart.id,
        "tile_uuid": tile_uuid,
        "query_identity": chart.model_dump(mode="json", by_alias=True, exclude_none=True),
        "dashboard_filter_identity": dashboard_filters.model_dump(mode="json", by_alias=True, exclude_none=True),
        "filters": normalized_filters,
        "drill_path": [item.model_dump(mode="json") for item in drill_path],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
