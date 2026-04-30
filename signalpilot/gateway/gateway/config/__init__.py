"""Public surface of the gateway config package.

Domain-specific settings classes and their cached accessor functions. Each domain
module only imports pydantic, pydantic_settings, and stdlib — no circular risk.

Dependency direction: gateway/config/* depends only on pydantic, pydantic_settings,
and stdlib. Nothing in gateway/ outside config/ is imported from inside config/.
All other gateway modules import FROM config/, never the reverse.

Class B env reads (those monkeypatched by tests) MUST remain as os.getenv / os.environ
in their original call sites. They are intentionally NOT migrated here. See architect.md
for the full two-class enumeration.
"""

from __future__ import annotations

from ._base import _GatewaySettingsBase as _GatewaySettingsBase  # for future extension; not in __all__
from .auth import AuthSettings, get_auth_settings
from .governance import GovernanceSettings, get_governance_settings
from .mcp import McpSettings, get_mcp_settings
from .network import NetworkSettings, get_network_settings
from .storage import StorageSettings, get_storage_settings

__all__ = [
    "AuthSettings",
    "get_auth_settings",
    "GovernanceSettings",
    "get_governance_settings",
    "StorageSettings",
    "get_storage_settings",
    "NetworkSettings",
    "get_network_settings",
    "McpSettings",
    "get_mcp_settings",
]
