"""Gateway auth package.

Re-exports the full public surface of the auth submodules so that
``from gateway.auth import …`` call sites continue to work unchanged.
"""

from .mcp_api_key import MCPAuthMiddleware, validate_api_key
from .user import (
    EXPECTED_AUDIENCE,
    JWT_LEEWAY_SECONDS,
    LOCAL_ORG_ID,
    LOCAL_USER_ID,
    DBSession,
    OrgAdmin,
    OrgID,
    OrgRole,
    UserID,
    require_org_admin,
    resolve_org_id,
    resolve_org_role,
    resolve_user_id,
)

__all__ = [
    "resolve_user_id",
    "resolve_org_id",
    "resolve_org_role",
    "require_org_admin",
    "UserID",
    "OrgID",
    "OrgRole",
    "OrgAdmin",
    "DBSession",
    "LOCAL_USER_ID",
    "LOCAL_ORG_ID",
    "EXPECTED_AUDIENCE",
    "JWT_LEEWAY_SECONDS",
    "MCPAuthMiddleware",
    "validate_api_key",
]
