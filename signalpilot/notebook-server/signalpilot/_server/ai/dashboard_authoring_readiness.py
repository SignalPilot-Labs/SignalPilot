from __future__ import annotations

import json
import os
from pathlib import Path

from signalpilot._server.ai.standalone_chat_tool_schemas import (
    DASHBOARD_AUTHORING_CONTRACT_VERSION,
)


def dashboard_authoring_readiness() -> tuple[bool, str | None]:
    plugin_path = os.getenv("SP_AGENT_PLUGIN_PATH", "").strip()
    if not plugin_path:
        return True, None
    root = Path(plugin_path)
    skill = root / "skills" / "dashboard-authoring" / "SKILL.md"
    manifest = root / ".claude-plugin" / "plugin.json"
    try:
        metadata = json.loads(manifest.read_text())
        skill_text = skill.read_text()
    except (OSError, ValueError, TypeError):
        return False, "dashboard_authoring_skill_unavailable"
    expected_version = os.getenv("SIGNALPILOT_PLUGIN_VERSION", "1.1.0").strip()
    if (
        metadata.get("version") != expected_version
        or DASHBOARD_AUTHORING_CONTRACT_VERSION not in skill_text
    ):
        return False, "dashboard_authoring_skill_contract_mismatch"
    return True, None
