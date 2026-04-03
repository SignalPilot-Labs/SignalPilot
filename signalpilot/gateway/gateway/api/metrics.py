"""Metrics SSE stream and connector capabilities endpoints."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .deps import ConnectionName, get_sandbox_client, load_settings, schema_cache
from ..governance.cache import query_cache
from ..store import get_connection, list_connections, list_sandboxes

router = APIRouter(prefix="/api")

# ─── SSE metrics stream ──────────────────────────────────────────────────────


@router.get("/metrics")
async def metrics_stream():
    """Server-Sent Events stream of live gateway metrics."""

    async def generate():
        while True:
            settings = load_settings()
            sandboxes = list_sandboxes()
            running = sum(1 for s in sandboxes if s.status == "running")

            sandbox_health = "unknown"
            try:
                client = get_sandbox_client()
                data = await client.health()
                sandbox_health = data.get("status", "unknown")
                kvm_available = data.get("kvm_available", False)
                active_vms = data.get("active_vms", 0)
                max_vms = data.get("max_vms", 10)
            except Exception:
                kvm_available = False
                active_vms = 0
                max_vms = 10

            payload = {
                "timestamp": time.time(),
                "sandbox_manager_configured": bool(settings.sandbox_manager_url),
                "sandbox_health": sandbox_health,
                "kvm_available": kvm_available,
                "active_sandboxes": len(sandboxes),
                "running_sandboxes": running,
                "active_vms": active_vms,
                "max_vms": max_vms,
                "connections": len(list_connections()),
                "query_cache": query_cache.stats(),
                "schema_cache": schema_cache.stats(),
            }

            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(generate(), media_type="text/event-stream")


# ─── Connector Tier Classification (HEX pattern) ──────────────────────────────

# HEX uses a 4-tier system:
#   Tier 1: Full support, actively maintained, all features
#   Tier 2: Stable, supported, may lag on new features
#   Tier 3: Supported, limited feature coverage
#   Community: Community-contributed, best-effort support

_CONNECTOR_TIERS = {
    "postgres": {
        "tier": 1,
        "label": "Tier 1 — Full Support",
        "features": {
            "ssl": True, "ssh_tunnel": True, "schema_introspection": True,
            "foreign_keys": True, "indexes": True, "row_counts": True,
            "column_stats": True, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": True,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": True, "parallel_schema": True,
            "table_sizes": True, "iam_auth": True,
        },
    },
    "mysql": {
        "tier": 1,
        "label": "Tier 1 — Full Support",
        "features": {
            "ssl": True, "ssh_tunnel": True, "schema_introspection": True,
            "foreign_keys": True, "indexes": True, "row_counts": True,
            "column_stats": True, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": False,
            "table_sizes": True, "iam_auth": True,
        },
    },
    "snowflake": {
        "tier": 1,
        "label": "Tier 1 — Full Support",
        "features": {
            "ssl": False, "ssh_tunnel": False, "schema_introspection": True,
            "foreign_keys": True, "indexes": False, "row_counts": True,
            "column_stats": False, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": True,
            "key_pair_auth": True, "oauth_auth": True, "warehouse_config": True,
            "table_sizes": True,
        },
    },
    "bigquery": {
        "tier": 1,
        "label": "Tier 1 — Full Support",
        "features": {
            "ssl": False, "ssh_tunnel": False, "schema_introspection": True,
            "foreign_keys": False, "indexes": False, "row_counts": True,
            "column_stats": False, "primary_keys": False, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": False,
            "partitioning_info": True, "clustering_info": True,
            "service_account_auth": True,
        },
    },
    "redshift": {
        "tier": 2,
        "label": "Tier 2 — Stable",
        "features": {
            "ssl": True, "ssh_tunnel": True, "schema_introspection": True,
            "foreign_keys": True, "indexes": False, "row_counts": True,
            "column_stats": True, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": True,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": True,
            "dist_sort_keys": True, "iam_auth": True, "table_sizes": True,
        },
    },
    "clickhouse": {
        "tier": 2,
        "label": "Tier 2 — Stable",
        "features": {
            "ssl": True, "ssh_tunnel": True, "schema_introspection": True,
            "foreign_keys": False, "indexes": False, "row_counts": True,
            "column_stats": True, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": False,
            "engine_info": True, "sorting_key_info": True,
            "native_and_http": True, "table_sizes": True,
        },
    },
    "databricks": {
        "tier": 2,
        "label": "Tier 2 — Stable",
        "features": {
            "ssl": False, "ssh_tunnel": False, "schema_introspection": True,
            "foreign_keys": True, "indexes": False, "row_counts": False,
            "column_stats": False, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": False,
            "unity_catalog": True, "pat_auth": True, "table_sizes": True,
        },
    },
    "mssql": {
        "tier": 2,
        "label": "Tier 2 — Stable",
        "features": {
            "ssl": True, "ssh_tunnel": True, "schema_introspection": True,
            "foreign_keys": True, "indexes": True, "row_counts": True,
            "column_stats": True, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": False,
            "table_sizes": True, "azure_ad_auth": True,
        },
    },
    "trino": {
        "tier": 2,
        "label": "Tier 2 — Stable",
        "features": {
            "ssl": True, "ssh_tunnel": False, "schema_introspection": True,
            "foreign_keys": True, "indexes": False, "row_counts": True,
            "column_stats": False, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": False,
            "federated_query": True,
        },
    },
    "duckdb": {
        "tier": 3,
        "label": "Tier 3 — Basic",
        "features": {
            "ssl": False, "ssh_tunnel": False, "schema_introspection": True,
            "foreign_keys": True, "indexes": False, "row_counts": True,
            "column_stats": False, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": False,
            "connection_pooling": False, "parallel_schema": False,
            "motherduck": True,
        },
    },
    "sqlite": {
        "tier": 3,
        "label": "Tier 3 — Basic",
        "features": {
            "ssl": False, "ssh_tunnel": False, "schema_introspection": True,
            "foreign_keys": True, "indexes": False, "row_counts": True,
            "column_stats": False, "primary_keys": True, "comments": False,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": False,
            "connection_pooling": False, "parallel_schema": False,
        },
    },
}


@router.get("/connectors/capabilities")
async def get_connector_capabilities(db_type: str | None = None):
    """Return connector tier classification and feature matrix.

    HEX-style tier system showing which features each connector supports.
    Useful for the frontend to show capability badges and for agents
    to understand what metadata is available per connection type.
    """
    if db_type:
        info = _CONNECTOR_TIERS.get(db_type)
        if not info:
            raise HTTPException(status_code=404, detail=f"Unknown db_type: {db_type}")
        feature_count = sum(1 for v in info["features"].values() if v)
        total_features = len(info["features"])
        return {
            "db_type": db_type,
            **info,
            "feature_score": round(feature_count / total_features * 100),
            "feature_count": feature_count,
            "total_features": total_features,
        }

    # Return all connectors grouped by tier
    tiers: dict[int, list] = {1: [], 2: [], 3: []}
    for dt, info in _CONNECTOR_TIERS.items():
        feature_count = sum(1 for v in info["features"].values() if v)
        total_features = len(info["features"])
        tiers[info["tier"]].append({
            "db_type": dt,
            **info,
            "feature_score": round(feature_count / total_features * 100),
            "feature_count": feature_count,
            "total_features": total_features,
        })

    return {
        "tier_1": tiers[1],
        "tier_2": tiers[2],
        "tier_3": tiers[3],
        "total_connectors": len(_CONNECTOR_TIERS),
    }


@router.get("/connections/{name}/capabilities")
async def get_connection_capabilities(name: ConnectionName):
    """Return capabilities for a specific connection based on its db_type.

    Combines tier info with live connection status for a complete picture.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    tier_info = _CONNECTOR_TIERS.get(info.db_type, {})
    features = tier_info.get("features", {})
    feature_count = sum(1 for v in features.values() if v)
    total_features = max(len(features), 1)

    # Check what's actually configured
    has_ssh = bool(info.ssh_tunnel and info.ssh_tunnel.enabled)
    has_ssl = bool(info.ssl or (info.ssl_config and info.ssl_config.enabled))
    has_schema_refresh = bool(info.schema_refresh_interval)

    return {
        "connection_name": name,
        "db_type": info.db_type,
        "tier": tier_info.get("tier", 3),
        "tier_label": tier_info.get("label", "Tier 3 — Basic"),
        "features": features,
        "feature_score": round(feature_count / total_features * 100),
        "configured": {
            "ssh_tunnel": has_ssh,
            "ssl": has_ssl,
            "schema_refresh": has_schema_refresh,
            "description": bool(info.description),
            "tags": bool(info.tags),
        },
    }
