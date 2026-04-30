from __future__ import annotations

from fastapi import HTTPException

from gateway.api.connections._router import router
from gateway.api.connections._tiers import _CONNECTOR_TIERS
from gateway.api.deps import StoreD
from gateway.auth import UserID
from gateway.scope_guard import RequireScope


@router.get("/connectors/capabilities", dependencies=[RequireScope("read")])
async def get_connector_capabilities(_: UserID, db_type: str | None = None):
    """Return connector tier classification and feature matrix."""
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

    tiers: dict[int, list] = {1: [], 2: [], 3: []}
    for dt, info in _CONNECTOR_TIERS.items():
        feature_count = sum(1 for v in info["features"].values() if v)
        total_features = len(info["features"])
        tiers[info["tier"]].append(
            {
                "db_type": dt,
                **info,
                "feature_score": round(feature_count / total_features * 100),
                "feature_count": feature_count,
                "total_features": total_features,
            }
        )

    return {
        "tier_1": tiers[1],
        "tier_2": tiers[2],
        "tier_3": tiers[3],
        "total_connectors": len(_CONNECTOR_TIERS),
    }


@router.get("/connections/{name}/capabilities", dependencies=[RequireScope("read")])
async def get_connection_capabilities(name: str, store: StoreD):
    """Return capabilities for a specific connection based on its db_type."""
    info = await store.get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    tier_info = _CONNECTOR_TIERS.get(info.db_type, {})
    features = tier_info.get("features", {})
    feature_count = sum(1 for v in features.values() if v)
    total_features = max(len(features), 1)

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
