"""Project context, credentials, MCP configuration, and prompt loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from signalpilot._server.auth.session_token import load_session_jwt

INSTRUCTIONS_PATH = Path(__file__).parent / "instructions.md"
PLACEHOLDER_SP_API_KEYS = {"", "sp_test_key_here"}


def _get_dbt_project_context(search_dir: str | None = None) -> str:
    from signalpilot._dbt.runner import (
        discover_dbt_projects,
        find_dbt_project,
        parse_dbt_project_yml,
    )

    project_dir = None
    for directory in [value for value in [search_dir, os.getcwd()] if value]:
        project_dir = find_dbt_project(directory)
        if project_dir:
            break
    if not project_dir and search_dir:
        projects = discover_dbt_projects(search_dir, max_depth=2)
        if projects:
            project_dir = projects[0].project_dir
    if not project_dir:
        projects = discover_dbt_projects(os.getcwd(), max_depth=2)
        if projects:
            project_dir = projects[0].project_dir
    if not project_dir:
        return ""

    info = parse_dbt_project_yml(project_dir)
    return (
        "# Active dbt project\n"
        f"path: {project_dir}\n"
        f"name: {info.project_name or 'unknown'}\n"
        f"profile: {info.profile or 'default'}\n"
        f"model_paths: {', '.join(info.model_paths)}\n\n"
        "IMPORTANT: Only work within this project directory. Do NOT search for "
        "or access dbt projects elsewhere on the machine. All file reads, writes, "
        f"and dbt commands must be scoped to {project_dir}."
    )


def _get_auth_config() -> dict[str, str]:
    """Get agent auth config from OAuth, API key, disk, or the gateway."""
    oauth = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "") or os.environ.get(
        "OAUTH_TOKEN", ""
    )
    if oauth:
        return {"type": "oauth", "token": oauth}
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        return {"type": "api_key", "token": api_key}

    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    credentials_path = (
        Path(config_dir) / ".credentials.json"
        if config_dir
        else Path.home() / ".claude" / ".credentials.json"
    )
    if credentials_path.is_file() and credentials_path.stat().st_size > 0:
        return {"type": "config_dir", "token": ""}

    try:
        import httpx

        from signalpilot._server.gateway_client import (
            gateway_headers,
            gateway_url,
        )

        response = httpx.get(
            f"{gateway_url()}/api/org/secrets/anthropic-key",
            headers=gateway_headers(),
            timeout=5.0,
        )
        if response.status_code == 200:
            key = response.json().get("anthropic_api_key", "")
            if isinstance(key, str) and key:
                return {"type": "api_key", "token": key}
    except Exception:
        pass

    raise ValueError(
        "No AI credentials configured. Set CLAUDE_CODE_OAUTH_TOKEN or "
        "ANTHROPIC_API_KEY, or ask your admin to add the Anthropic API key "
        "on the integrations page."
    )


def _apply_auth_config(
    agent_env: dict[str, str],
    auth_config: dict[str, str] | None,
) -> None:
    """Apply one execution credential and override inherited competitors.

    The Agent SDK merges ``options.env`` over ``os.environ``. Empty values are
    required here: deleting a competing key would let its inherited value
    reappear in the Claude CLI subprocess.
    """
    if not auth_config:
        return
    if auth_config["type"] == "oauth":
        agent_env["ANTHROPIC_API_KEY"] = ""
        agent_env["ANTHROPIC_AUTH_TOKEN"] = ""
        agent_env["OAUTH_TOKEN"] = ""
        agent_env["CLAUDE_CODE_OAUTH_TOKEN"] = auth_config["token"]
    elif auth_config["type"] == "api_key":
        agent_env["CLAUDE_CODE_OAUTH_TOKEN"] = ""
        agent_env["OAUTH_TOKEN"] = ""
        agent_env["ANTHROPIC_AUTH_TOKEN"] = ""
        agent_env["ANTHROPIC_API_KEY"] = auth_config["token"]


def _get_oauth_token() -> str:
    """Backward-compatible credential accessor."""
    return _get_auth_config()["token"]


def _get_mcp_servers_config(
    mcp_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from signalpilot._utils.localhost import fix_localhost_url

    servers: dict[str, Any] = {}
    gateway_url = os.environ.get("SP_GATEWAY_MCP_URL")
    if not gateway_url:
        gateway_url = os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")
        if not gateway_url.rstrip("/").endswith("/mcp"):
            gateway_url = f"{gateway_url.rstrip('/')}/mcp"
    gateway_url = fix_localhost_url(gateway_url)
    auth_token = load_session_jwt() or _normalized_sp_api_key(
        os.environ.get("SP_API_KEY", "")
    )
    if auth_token or _is_local_url(gateway_url):
        signalpilot_server: dict[str, Any] = {
            "type": "http",
            "url": gateway_url,
        }
        if auth_token:
            signalpilot_server["headers"] = {
                "Authorization": f"Bearer {auth_token}"
            }
        servers["signalpilot"] = signalpilot_server
    if mcp_config:
        try:
            from signalpilot._server.ai.mcp.config import append_presets

            mcp_config = append_presets(mcp_config)  # type: ignore[arg-type]
        except Exception:
            pass
        for name, config in mcp_config.get("mcpServers", {}).items():
            if config.get("disabled"):
                continue
            if "command" in config:
                server: dict[str, Any] = {
                    "type": "stdio",
                    "command": config["command"],
                }
                if config.get("args"):
                    server["args"] = config["args"]
                if config.get("env"):
                    server["env"] = config["env"]
                servers[name] = server
            elif "url" in config:
                server = {
                    "type": config.get("type", "http"),
                    "url": config["url"],
                }
                if config.get("headers"):
                    server["headers"] = config["headers"]
                servers[name] = server
    return servers


def _normalized_sp_api_key(value: str) -> str:
    stripped = value.strip()
    return "" if stripped in PLACEHOLDER_SP_API_KEYS else stripped


def _is_local_url(url: str) -> bool:
    return urlparse(url).hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "gateway",
    }


def _get_system_prompt() -> str:
    if INSTRUCTIONS_PATH.exists():
        return INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    return "You are an AI assistant helping with a reactive Python notebook."
