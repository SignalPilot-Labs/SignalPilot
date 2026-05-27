from __future__ import annotations

import logging
import os
from dataclasses import dataclass


@dataclass
class GlobalSettings:
    DEVELOPMENT_MODE: bool = False
    QUIET: bool = False
    YES: bool = False
    CHECK_STATUS_UPDATE: bool = False
    TRACING: bool = os.getenv("SP_TRACING", "false") in ("true", "1")
    PROFILE_DIR: str | None = None
    LOG_LEVEL: int = logging.WARNING
    MANAGE_SCRIPT_METADATA: bool = os.getenv(
        "SP_MANAGE_SCRIPT_METADATA", "false"
    ) in ("true", "1")
    IN_SECURE_ENVIRONMENT: bool = os.getenv(
        "SP_IN_SECURE_ENVIRONMENT", "false"
    ) in ("true", "1")
    # Disable authentication on the virtual file endpoint (`/@file/...`).
    # Useful in sandboxed/embedded deployments where virtual file URLs need
    # to be fetched in trusted contexts. Default "false", meaning auth is required.
    DISABLE_AUTH_ON_VIRTUAL_FILES: bool = os.getenv(
        "_SIGNALPILOT_DISABLE_AUTH_ON_VIRTUAL_FILES", "false"
    ) in ("true", "1")


GLOBAL_SETTINGS = GlobalSettings()
