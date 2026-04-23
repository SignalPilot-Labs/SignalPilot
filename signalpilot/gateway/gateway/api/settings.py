"""Gateway settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ..models import GatewaySettings
from ..scope_guard import RequireScope
from .deps import StoreD, reset_sandbox_client

REDACTED_MASK = "****"

router = APIRouter(prefix="/api")


def _redact_settings(settings: GatewaySettings) -> GatewaySettings:
    """Return a copy of settings with secret fields masked.

    Mask pattern: truthy value -> REDACTED_MASK, falsy value -> None.
    This prevents API keys from leaking in responses while preserving
    the distinction between set and unset.
    """
    return settings.model_copy(update={
        "sandbox_api_key": REDACTED_MASK if settings.sandbox_api_key else None,
        "api_key": REDACTED_MASK if settings.api_key else None,
    })


@router.get("/settings", dependencies=[RequireScope("admin")])
async def get_settings(store: StoreD) -> GatewaySettings:
    settings = await store.load_settings()
    return _redact_settings(settings)


@router.put("/settings", dependencies=[RequireScope("admin")])
async def update_settings(settings: GatewaySettings, store: StoreD) -> GatewaySettings:
    # Prevent mask round-trip: if the client sends back the redacted mask
    # (from a GET-modify-PUT cycle), preserve the existing stored value.
    existing = await store.load_settings()
    if settings.api_key == REDACTED_MASK:
        settings = settings.model_copy(update={"api_key": existing.api_key})
    if settings.sandbox_api_key == REDACTED_MASK:
        settings = settings.model_copy(update={"sandbox_api_key": existing.sandbox_api_key})
    await store.save_settings(settings)
    reset_sandbox_client()  # Reconnect with new URL
    return _redact_settings(settings)
