"""Auth package for the Workspaces API.

Exports:
  current_user_id  — FastAPI dependency function
  CurrentUserId    — Annotated type alias for use in route signatures
  JwksClient       — JWKS client class (instantiated in lifespan, stored on app.state)
"""

from workspaces_api.auth.clerk import JwksClient
from workspaces_api.auth.dependency import CurrentUserId, current_user_id

__all__ = ["JwksClient", "CurrentUserId", "current_user_id"]
