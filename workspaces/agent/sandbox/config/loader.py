"""Config loader for AutoFyn.

Resolution order (later overrides earlier):
  1. Built-in defaults (config/config.yml in repo)
  2. ~/.autofyn/config.yml (global user config)
  3. .autofyn/config.yml (per-project config)
  4. Environment variables (AF_* prefix, highest priority)

On first run, copies the default config to .autofyn/config.yml so the
user has a visible, editable file.
"""

import logging
import os
import shutil
from pathlib import Path

import yaml

log = logging.getLogger("config")

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_CONFIG = _REPO_ROOT / "config" / "config.yml"
_GLOBAL_CONFIG = Path.home() / ".autofyn" / "config.yml"
_PROJECT_CONFIG = _REPO_ROOT / ".autofyn" / "config.yml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, recursing into nested dicts."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path) -> dict:
    """Load a YAML file, return empty dict if missing or invalid."""
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _ensure_gitignore_entry() -> None:
    """Append .autofyn/ to .gitignore if not already listed."""
    gitignore = _REPO_ROOT / ".gitignore"
    entry = ".autofyn/"
    if gitignore.exists():
        content = gitignore.read_text()
        if entry in content.splitlines():
            return
        if not content.endswith("\n"):
            content += "\n"
        gitignore.write_text(content + entry + "\n")
    else:
        gitignore.write_text(entry + "\n")
    log.info("Added %s to %s", entry, gitignore)


def _ensure_project_config() -> None:
    """Copy default config to .autofyn/config.yml on first run."""
    if _PROJECT_CONFIG.exists():
        return
    if not _DEFAULT_CONFIG.exists():
        return
    _PROJECT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_DEFAULT_CONFIG, _PROJECT_CONFIG)
    _ensure_gitignore_entry()
    log.info("Created %s from defaults", _PROJECT_CONFIG)


def _apply_env_overrides(config: dict) -> dict:
    """Override config sections from environment variables."""
    # Sandbox overrides (AF_* prefix)
    sandbox = config.get("sandbox", {})
    sandbox_env_map = {
        "AF_SANDBOX_URL": ("url", str),
        "AF_MAX_VMS": ("max_vms", int),
        "AF_VM_MEMORY_MB": ("vm_memory_mb", int),
        "AF_VM_VCPUS": ("vm_vcpus", int),
        "AF_VM_TIMEOUT_SEC": ("vm_timeout_sec", int),
        "AF_EXEC_TIMEOUT_SEC": ("exec_timeout_sec", int),
        "AF_CLONE_TIMEOUT_SEC": ("clone_timeout_sec", int),
        "AF_NPM_TIMEOUT_SEC": ("npm_timeout_sec", int),
        "AF_LOG_LEVEL": ("log_level", str),
        "AF_ALLOW_DOCKER": ("allow_docker", lambda v: v.lower() in ("1", "true", "yes")),
    }
    for env_var, (key, cast) in sandbox_env_map.items():
        val = os.getenv(env_var)
        if val is not None:
            sandbox[key] = cast(val)
    config["sandbox"] = sandbox

    # Database password override
    db = config.get("database", {})
    db_password = os.getenv("DB_PASSWORD")
    if db_password is not None:
        db["password"] = db_password
    config["database"] = db

    return config


def load() -> dict:
    """Load merged config from all sources."""
    _ensure_project_config()
    config = _load_yaml(_DEFAULT_CONFIG)
    config = _deep_merge(config, _load_yaml(_GLOBAL_CONFIG))
    config = _deep_merge(config, _load_yaml(_PROJECT_CONFIG))
    config = _apply_env_overrides(config)
    return config


def sandbox_config() -> dict:
    """Load just the sandbox section."""
    return load().get("sandbox", {})


_REQUIRED_DB_KEYS = {
    "host",
    "port",
    "name",
    "user",
    "password",
    "pool_size",
    "max_overflow",
    "pool_timeout",
    "pool_recycle",
    "echo",
}


def database_config() -> dict:
    """Load just the database section. Raises if missing or incomplete."""
    cfg = load().get("database")
    if not cfg:
        raise RuntimeError("Missing 'database' section in config.yml")
    missing = _REQUIRED_DB_KEYS - set(cfg.keys())
    if missing:
        raise RuntimeError(
            f"Missing database config keys: {', '.join(sorted(missing))}"
        )
    return cfg


def security_config() -> dict:
    """Load just the security section."""
    return load().get("security", {})
