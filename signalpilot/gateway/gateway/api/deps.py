"""Shared dependencies for all API routers.

Centralizes repeated patterns:
- Store dependency (DB-backed, user-scoped)
- Schema fetch-or-cache boilerplate
- Connection lookup with 404
- Error sanitization
- Schema filtering
- Sandbox client management
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import os
import re
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

from ..auth import DBSession, OrgID, UserID
from ..billing.entitlements import OrgEntitlement, get_entitlement
from ..connectors.pool_manager import pool_manager
from ..connectors.schema_cache import schema_cache
from ..network import SandboxClient
from ..store import Store

# Store dependency.


async def get_store(
    request: Request,
    org_id: OrgID,
    user_id: UserID,
    db: DBSession,
) -> Store:
    """FastAPI dependency: yields a Store scoped to the current org."""
    auth = getattr(request.state, "auth", None) or {}
    claims = getattr(request.state, "_jwt_claims", {}) or {}
    execution_identity = claims.get("execution_identity")
    allowed_connection_name = (
        claims.get("connection_name")
        if isinstance(execution_identity, str) and execution_identity.startswith("chat:")
        else None
    )
    return Store(
        db,
        org_id=org_id,
        user_id=user_id,
        eval_connection=auth.get("eval_connection"),
        allowed_connection_name=allowed_connection_name,
        execution_identity=execution_identity if isinstance(execution_identity, str) else None,
    )


StoreD = Annotated[Store, Depends(get_store)]


# Gating dependencies.
#
# Two questions, two dependencies, nothing else:
#   RequireBillablePlan             may this org use the feature?   402 plan_required
#   RequireDeploymentCapability(n)  can this deployment run it?     503 not_available_in_deployment
# Org role (OrgAdmin) and key scope (RequireScope) are separate concerns and stay as they are.


class GatingError(HTTPException):
    """A plan or deployment refusal with a machine-readable body.

    ``detail`` is the dict body; ``register_routers`` installs a handler that
    also lifts its keys to the top level (``{"error": ..., "tier": ...}``).
    """


def plan_required_error(tier: str) -> GatingError:
    return GatingError(status_code=402, detail={"error": "plan_required", "tier": tier})


def not_available_error(capability: str) -> GatingError:
    return GatingError(status_code=503, detail={"error": "not_available_in_deployment", "capability": capability})


async def require_billable_plan(org_id: OrgID) -> OrgEntitlement:
    """FastAPI dependency: the one gating rule.

    Resolves the org's entitlement and raises 402 ``plan_required`` unless the
    org is on a billable plan. Local mode resolves to ``unlimited`` and passes.
    Returns the entitlement so a route can read allowances from it.
    """
    from ..store.orgs import ensure_gateway_org

    entitlement = await get_entitlement(org_id)
    await ensure_gateway_org(org_id)
    if not entitlement.is_billable:
        raise plan_required_error(entitlement.tier)
    return entitlement


RequireBillablePlan = Depends(require_billable_plan)
BillableEntitlement = Annotated[OrgEntitlement, Depends(require_billable_plan)]

DEPLOYMENT_CAPABILITIES: tuple[str, ...] = ("evals", "sandbox")


def deployment_capabilities() -> dict[str, bool]:
    """What this deployment is wired to run, independent of any org's plan.

    ``evals``: an eval runner image plus its execution backend and evidence
    store are configured. ``sandbox``: the ephemeral sandbox runtime has
    credentials. Read at call time so tests and reloads see current settings.
    """
    from ..config.evals import get_eval_run_settings
    from ..config.sandbox_runtime import get_sandbox_runtime_settings

    return {
        "evals": get_eval_run_settings().capable,
        "sandbox": get_sandbox_runtime_settings().enabled,
    }


_capability_dependencies: dict[str, Any] = {}


def RequireDeploymentCapability(name: str):  # capitalised on purpose: it reads like the other gate names
    """Dependency factory: 503 ``not_available_in_deployment`` unless ``name`` is wired up."""
    if name not in DEPLOYMENT_CAPABILITIES:
        raise ValueError(f"unknown deployment capability {name!r}")
    if name not in _capability_dependencies:

        async def _require_capability() -> None:
            if not deployment_capabilities()[name]:
                raise not_available_error(name)

        _require_capability.__name__ = f"require_deployment_capability_{name}"
        _require_capability.__qualname__ = _require_capability.__name__
        _capability_dependencies[name] = Depends(_require_capability)
    return _capability_dependencies[name]


def require_deployment_capability_call(name: str):
    """The underlying callable for ``RequireDeploymentCapability(name)`` (for dependency overrides)."""
    return RequireDeploymentCapability(name).dependency


# Error sanitization.

_SENSITIVE_PATTERNS = [
    re.compile(r"postgresql://[^\s]+", re.IGNORECASE),
    re.compile(r"mysql://[^\s]+", re.IGNORECASE),
    re.compile(r"redshift://[^\s]+", re.IGNORECASE),
    re.compile(r"clickhouse://[^\s]+", re.IGNORECASE),
    re.compile(r"snowflake://[^\s]+", re.IGNORECASE),
    re.compile(r"databricks://[^\s]+", re.IGNORECASE),
    re.compile(r"password[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"host=\S+", re.IGNORECASE),
    re.compile(r"access_token[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"private_key[=:]\s*\S+", re.IGNORECASE),
]


def sanitize_db_error(error: str, db_type: str | None = None) -> str:
    sanitized = error
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    if len(sanitized) > 500:
        sanitized = sanitized[:500] + "..."

    err_lower = sanitized.lower()
    hints: list[str] = []

    if "connection refused" in err_lower or "could not connect" in err_lower:
        hints.append("Check that the database server is running and the host/port are correct")
        if db_type in ("postgres", "mysql", "redshift"):
            hints.append("Verify firewall rules allow connections from this server's IP")
    elif "authentication" in err_lower or "password" in err_lower or "access denied" in err_lower:
        hints.append("Verify username and password are correct")
    elif "timeout" in err_lower or "timed out" in err_lower:
        hints.append("Database is unreachable — check network connectivity")
    elif "ssl" in err_lower or "certificate" in err_lower or "tls" in err_lower:
        hints.append("SSL/TLS connection failed — check SSL configuration")
    elif "permission denied" in err_lower or "insufficient privileges" in err_lower:
        hints.append("User lacks required permissions")

    if hints:
        sanitized += " | Hint: " + "; ".join(hints)
    return sanitized


# Connection lookup.


async def require_connection(store: Store, name: str):
    """Look up connection by name, raise 404 if not found."""
    info = await store.get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    return info


# Schema fetch-or-cache.


async def get_or_fetch_schema(store: Store, name: str, info=None, force_refresh: bool = False) -> dict[str, Any]:
    if info is None:
        info = await require_connection(store, name)

    if not force_refresh:
        cached = schema_cache.get(name)
        if cached is not None:
            return cached

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    try:
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
            schema = await connector.get_schema()
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e), info.db_type))

    schema_cache.put(name, schema)
    return schema


async def apply_filters(store: Store, name: str, schema: dict[str, Any]) -> dict[str, Any]:
    filtered = await store.apply_endorsement_filter(name, schema)
    sf_include, sf_exclude = await get_schema_filters(store, name)
    return apply_schema_filter(filtered, sf_include, sf_exclude)


async def get_filtered_schema(store: Store, name: str, info=None, force_refresh: bool = False) -> dict[str, Any]:
    raw = await get_or_fetch_schema(store, name, info, force_refresh)
    return await apply_filters(store, name, raw)


# Schema filtering.


def apply_schema_filter(
    schema: dict[str, dict],
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> dict[str, dict]:
    if not include and not exclude:
        return schema
    filtered: dict[str, dict] = {}
    for key, table_data in schema.items():
        table_schema = table_data.get("schema", "")
        if include:
            if not any(fnmatch.fnmatch(table_schema.lower(), pat.lower()) for pat in include):
                continue
        if exclude:
            if any(fnmatch.fnmatch(table_schema.lower(), pat.lower()) for pat in exclude):
                continue
        filtered[key] = table_data
    return filtered


async def get_schema_filters(store: Store, name: str) -> tuple[list[str], list[str]]:
    conn = await store.get_connection(name)
    if conn is None:
        return [], []
    include = getattr(conn, "schema_filter_include", []) or []
    exclude = getattr(conn, "schema_filter_exclude", []) or []
    return include, exclude


# Sandbox client.

# Sandbox endpoint + credentials are org-scoped settings, so clients are cached
# per org and per resolved config: never shared across orgs.
_sandbox_clients: dict[str, tuple[str, SandboxClient]] = {}
_platform_sandbox_client: SandboxClient | None = None

_UNSCOPED_ORG_KEY = "\x00unscoped"


def _sandbox_config_fingerprint(settings) -> str:
    """Identity of the resolved sandbox config: endpoint + credential."""
    key = settings.sandbox_api_key or ""
    cred = hashlib.sha256(key.encode()).hexdigest() if key else "-"
    return f"{settings.sandbox_manager_url}\x00{cred}"


def _close_in_background(client: SandboxClient) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    asyncio.create_task(client.close())


async def get_sandbox_client_with_store(store: Store) -> SandboxClient:
    settings = await store.load_settings()
    org_key = store.org_id or _UNSCOPED_ORG_KEY
    fingerprint = _sandbox_config_fingerprint(settings)

    cached = _sandbox_clients.get(org_key)
    if cached is not None:
        if cached[0] == fingerprint:
            return cached[1]
        _close_in_background(cached[1])
        del _sandbox_clients[org_key]

    client = SandboxClient(
        base_url=settings.sandbox_manager_url,
        api_key=settings.sandbox_api_key,
    )
    _sandbox_clients[org_key] = (fingerprint, client)
    return client


def get_sandbox_client() -> SandboxClient:
    """Return the platform sandbox client for a caller without organization context.

    Do not expose an organization BYOS endpoint when the request has no organization.
    """
    global _platform_sandbox_client
    if _platform_sandbox_client is None:
        url = os.environ.get("SP_SANDBOX_MANAGER_URL")
        if not url:
            raise HTTPException(status_code=503, detail="Sandbox client not initialized")
        _platform_sandbox_client = SandboxClient(base_url=url, is_platform=True)
    return _platform_sandbox_client


def reset_sandbox_client(org_id: str | None = None) -> None:
    """Drop one org's cached client. Never touches another org's entry."""
    entry = _sandbox_clients.pop(org_id or _UNSCOPED_ORG_KEY, None)
    if entry is not None:
        _close_in_background(entry[1])


async def close_sandbox_clients() -> None:
    global _platform_sandbox_client
    for _, client in _sandbox_clients.values():
        await client.close()
    _sandbox_clients.clear()
    if _platform_sandbox_client is not None:
        await _platform_sandbox_client.close()
        _platform_sandbox_client = None
