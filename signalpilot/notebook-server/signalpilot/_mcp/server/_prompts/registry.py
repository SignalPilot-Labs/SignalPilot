"""Registry of all supported MCP prompts."""

from signalpilot._mcp.server._prompts.base import PromptBase
from signalpilot._mcp.server._prompts.prompts.errors import ErrorsSummary
from signalpilot._mcp.server._prompts.prompts.notebooks import ActiveNotebooks

SUPPORTED_MCP_PROMPTS: list[type[PromptBase]] = [
    ActiveNotebooks,
    ErrorsSummary,
]
