from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from signalpilot import _loggers
from signalpilot._config.config import PartialSignalPilotConfig
from signalpilot._utils.toml import toml_reader

LOGGER = _loggers.sp_logger()


def read_signalpilot_config(path: str) -> PartialSignalPilotConfig:
    """Read the sp.toml configuration."""
    return cast(PartialSignalPilotConfig, toml_reader.read(path))


def read_pyproject_signalpilot_config(
    pyproject_path: str | Path,
) -> PartialSignalPilotConfig | None:
    """Read the sp tool config from a pyproject.toml file."""
    pyproject_config = toml_reader.read(pyproject_path)
    signalpilot_tool_config = get_signalpilot_config_from_pyproject_dict(
        pyproject_config
    )
    if signalpilot_tool_config is None:
        return None
    LOGGER.info("Found sp config in pyproject.toml at %s", pyproject_path)
    return signalpilot_tool_config


def sanitize_pyproject_dict(
    pyproject_dict: dict[str, Any], keys: tuple[tuple[str, ...], ...]
) -> dict[str, Any]:
    """Sanitize the pyproject.toml dictionary by removing specified keys."""
    for key_path in keys:
        current_level = pyproject_dict
        for key in key_path[:-1]:
            if key in current_level and isinstance(current_level[key], dict):
                current_level = current_level[key]
            else:
                return pyproject_dict
        if current_level and key_path[-1] in current_level:
            LOGGER.warning(
                "%s in script metadata is ignored for security reasons",
                ".".join(key_path),
            )
            del current_level[key_path[-1]]
    return pyproject_dict


def get_signalpilot_config_from_pyproject_dict(
    pyproject_dict: dict[str, Any],
) -> PartialSignalPilotConfig | None:
    """Get the sp config from a pyproject.toml dictionary."""
    signalpilot_tool_config = pyproject_dict.get("tool", {}).get("sp", None)
    if signalpilot_tool_config is None:
        return None
    if not isinstance(signalpilot_tool_config, dict):
        LOGGER.warning(
            "pyproject.toml contains invalid sp config: %s",
            signalpilot_tool_config,
        )
        return None
    return cast(PartialSignalPilotConfig, signalpilot_tool_config)


def find_nearest_pyproject_toml(
    start_path: str | Path,
) -> Path | None:
    """Find the nearest pyproject.toml file."""
    path = Path(start_path)
    root = path.anchor
    try:
        while not path.joinpath("pyproject.toml").exists():
            if str(path) == root:
                return None
            if path.parent == path:
                return None
            path = path.parent
    except OSError:
        return None
    return path.joinpath("pyproject.toml")
