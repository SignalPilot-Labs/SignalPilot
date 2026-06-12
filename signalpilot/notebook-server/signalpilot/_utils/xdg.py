from __future__ import annotations

import os
from pathlib import Path


def home_path() -> Path:
    """Get home directory or temp directory if home directory is not available.

    Returns:
        Path: The home directory.
    """
    try:
        return Path.home().resolve()
    except RuntimeError:
        # Can't get home directory, so use temp directory
        return Path("/tmp")


def xdg_config_home() -> Path:
    """Get XDG config home directory.

    Returns $XDG_CONFIG_HOME if set and non-empty, otherwise ~/.config
    """
    xdg_config_home_env = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home_env and xdg_config_home_env.strip():
        return Path(xdg_config_home_env)
    return home_path() / ".config"


def xdg_cache_home() -> Path:
    """Get XDG cache home directory.

    Returns $XDG_CACHE_HOME if set and non-empty, otherwise ~/.cache
    """
    xdg_cache_home_env = os.getenv("XDG_CACHE_HOME")
    if xdg_cache_home_env and xdg_cache_home_env.strip():
        return Path(xdg_cache_home_env)
    return home_path() / ".cache"


def xdg_state_home() -> Path:
    """Get XDG state home directory.

    Returns $XDG_STATE_HOME if set and non-empty, otherwise ~/.local/state
    """
    if os.name == "posix":
        xdg_state_home_env = os.getenv("XDG_STATE_HOME")
        if xdg_state_home_env and xdg_state_home_env.strip():
            return Path(xdg_state_home_env)
        return home_path() / ".local" / "state"
    else:
        return home_path()


def sp_config_path() -> Path:
    """Get sp config file path using XDG specification.

    $XDG_CONFIG_HOME/signalpilot/signalpilot.toml if set, otherwise ~/.config/signalpilot/signalpilot.toml
    """
    return xdg_config_home() / "sp" / "sp.toml"


def sp_cache_dir() -> Path:
    """Get sp cache directory using XDG specification.

    $XDG_CACHE_HOME/signalpilot if set, otherwise ~/.cache/signalpilot
    """
    return xdg_cache_home() / "sp"


def sp_state_dir() -> Path:
    """Get sp state directory using XDG specification.

    On Linux/macOS/Unix, returns:
    $XDG_STATE_HOME/signalpilot if set, otherwise ~/.local/state/signalpilot

    On Windows, returns:
    ~/.sp
    """
    if os.name == "posix":
        return xdg_state_home() / "sp"
    else:
        return home_path() / ".sp"


def sp_log_dir() -> Path:
    """Get sp log directory using XDG specification.

    $XDG_CACHE_HOME/signalpilot/logs if set, otherwise ~/.cache/signalpilot/logs
    """
    return sp_cache_dir() / "logs"
