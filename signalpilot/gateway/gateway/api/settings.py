"""Gateway settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..auth import OrgAdmin
from ..models import GatewaySettings
from ..models.settings import MCPAgentDefaults
from ..security.scope_guard import RequireScope
from .deps import StoreD, reset_sandbox_client

REDACTED_MASK = "****"

router = APIRouter(prefix="/api")


def _redact_settings(settings: GatewaySettings) -> GatewaySettings:
    """Return a copy of settings with secret fields masked.

    Mask pattern: truthy value -> REDACTED_MASK, falsy value -> None.
    This prevents API keys from leaking in responses while preserving
    the distinction between set and unset.
    """
    return settings.model_copy(
        update={
            "sandbox_api_key": REDACTED_MASK if settings.sandbox_api_key else None,
            "api_key": REDACTED_MASK if settings.api_key else None,
        }
    )


@router.get("/settings", dependencies=[RequireScope("admin")])
async def get_settings(store: StoreD) -> GatewaySettings:
    settings = await store.load_settings()
    return _redact_settings(settings)


@router.put("/settings", dependencies=[RequireScope("admin")])
async def update_settings(settings: GatewaySettings, store: StoreD, _role: OrgAdmin) -> GatewaySettings:
    # Prevent mask round-trip: if the client sends back the redacted mask
    # (from a GET-modify-PUT cycle), preserve the existing stored value.
    existing = await store.load_settings()
    # Older full-settings clients do not know these defaults. Preserve omitted fields.
    settings = settings.model_copy(
        update={
            name: getattr(existing, name)
            for name in MCPAgentDefaults.model_fields
            if name not in settings.model_fields_set
        }
    )
    if settings.api_key == REDACTED_MASK:
        settings = settings.model_copy(update={"api_key": existing.api_key})
    if settings.sandbox_api_key == REDACTED_MASK:
        settings = settings.model_copy(update={"sandbox_api_key": existing.sandbox_api_key})
    await store.save_settings(settings)
    reset_sandbox_client(store.org_id)  # Reconnect with new URL
    return _redact_settings(settings)


@router.get("/settings/mcp-agent", dependencies=[RequireScope("admin")])
async def get_mcp_agent_defaults(store: StoreD) -> MCPAgentDefaults:
    settings = await store.load_settings()
    return MCPAgentDefaults.model_validate(settings.model_dump())


@router.put("/settings/mcp-agent", dependencies=[RequireScope("admin")])
async def update_mcp_agent_defaults(defaults: MCPAgentDefaults, store: StoreD, _role: OrgAdmin) -> MCPAgentDefaults:
    if defaults.mcp_agent_default_project_id:
        project = await store.get_workspace_project(defaults.mcp_agent_default_project_id)
        if project is None or project.status != "active":
            raise HTTPException(400, "Select an active workspace project belonging to this account")
        if (
            defaults.mcp_agent_default_connection_name
            and defaults.mcp_agent_default_connection_name != project.connection_name
        ):
            raise HTTPException(400, "Select the project's configured Chats connection, or leave the connection default empty")
    elif defaults.mcp_agent_default_branch:
        raise HTTPException(400, "Select a default project before setting a default branch")
    if (
        defaults.mcp_agent_default_connection_name
        and await store.get_connection(defaults.mcp_agent_default_connection_name) is None
    ):
        raise HTTPException(400, "Select a database connection belonging to this account")
    existing = await store.load_settings()
    await store.save_settings(existing.model_copy(update=defaults.model_dump()))
    return defaults
