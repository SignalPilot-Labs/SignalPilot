from __future__ import annotations

from dataclasses import dataclass

from signalpilot import _loggers
from signalpilot._server.ai.tools.base import ToolBase
from signalpilot._server.ai.tools.notebook_types import (
    EmptyArgs,
    SuccessResult,
    ToolGuidelines,
)
from signalpilot._utils import requests
from signalpilot._utils.paths import sp_package_path

LOGGER = _loggers.sp_logger()

# We ship the rules with the package in _static/CLAUDE.md
# If the file doesn't exist (development or edge cases), we fallback to fetching from the URL
SP_RULES_URL = "https://docs.signalpilot.ai/docs/"
SP_RULES_PATH = sp_package_path() / "_static" / "CLAUDE.md"


@dataclass
class GetSignalPilotRulesOutput(SuccessResult):
    rules_content: str | None = None
    source_url: str = SP_RULES_URL


class GetSignalPilotRules(ToolBase[EmptyArgs, GetSignalPilotRulesOutput]):
    """Get the official sp rules and guidelines for AI assistants.

    Returns:
        The content of the rules file.
    """

    guidelines = ToolGuidelines(
        when_to_use=[
            "Before using other sp mcp tools, reading a sp notebook, or writing to a notebook ALWAYS use this first to understand how sp works",
        ],
        avoid_if=[
            "The rules have already been retrieved recently, as they rarely change",
        ],
    )

    def handle(self, args: EmptyArgs) -> GetSignalPilotRulesOutput:
        del args

        # First, try to load from the bundled file
        if SP_RULES_PATH.exists():
            try:
                rules_content = SP_RULES_PATH.read_text(encoding="utf-8")
                return GetSignalPilotRulesOutput(
                    rules_content=rules_content,
                    source_url="bundled",
                    next_steps=[
                        "Follow the guidelines in the rules when working with sp notebooks",
                    ],
                )
            except Exception as e:
                LOGGER.warning(
                    "Failed to read bundled sp rules from %s: %s",
                    SP_RULES_PATH,
                    str(e),
                )
                # Fall through to fetch from URL

        # Fallback: fetch from the URL
        try:
            response = requests.get(SP_RULES_URL, timeout=10)
            response.raise_for_status()

            return GetSignalPilotRulesOutput(
                rules_content=response.text(),
                source_url=SP_RULES_URL,
                next_steps=[
                    "Follow the guidelines in the rules when working with sp notebooks",
                ],
            )

        except Exception as e:
            LOGGER.warning(
                "Failed to fetch sp rules from %s: %s",
                SP_RULES_URL,
                str(e),
            )

            return GetSignalPilotRulesOutput(
                status="error",
                message=f"Failed to fetch sp rules: {e!s}",
                source_url=SP_RULES_URL,
                next_steps=[
                    "Check internet connectivity",
                    "Verify the rules URL is accessible",
                    "Try again later if the service is temporarily unavailable",
                ],
            )
