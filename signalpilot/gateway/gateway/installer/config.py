"""Configuration cascade — defaults → repo → user → project → env."""

import copy
import os
from pathlib import Path

import yaml

_DEFAULTS: dict = {
    "database": {"host": "localhost", "port": 5600, "user": "postgres", "password": "postgres", "name": "signalpilot"},
    "gateway": {"host": "0.0.0.0", "port": 3300},
    "web": {"port": 3200},
    "sandbox": {"provider": "auto", "max_vms": 4, "vm_memory_mb": 512, "vm_vcpus": 1},
    "agent": {"port": 8500, "max_budget_usd": 0},
    "monitor": {"port": 3400, "api_port": 3401},
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_yaml(path: Path) -> dict:
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        import sys
        print(f"  warning: failed to parse {path}: {exc}", file=sys.stderr)
        return {}


def _parse_env_overrides(reference: dict) -> list[tuple[str, str, object]]:
    """Parse SP_* env vars into (section, key, coerced_value) triples.

    Uses *reference* to determine valid sections/keys and whether to
    coerce to int.  Shared by load_config and resolve_with_sources.
    """
    overrides: list[tuple[str, str, object]] = []
    for env_key, env_val in os.environ.items():
        if not env_key.startswith("SP_"):
            continue
        parts = env_key[3:].lower().split("_", 1)
        if len(parts) != 2:
            continue
        section, key = parts
        if section not in reference or not isinstance(reference[section], dict):
            continue
        if key not in reference[section]:
            continue
        default_val = reference[section][key]
        if isinstance(default_val, int):
            try:
                overrides.append((section, key, int(env_val)))
            except ValueError:
                pass
        else:
            overrides.append((section, key, env_val))
    return overrides


def _apply_env(config: dict) -> dict:
    result = copy.deepcopy(config)
    for section, key, value in _parse_env_overrides(_DEFAULTS):
        if section in result and isinstance(result[section], dict) and key in result[section]:
            result[section][key] = value
    return result


def _load_layers(repo_root: Path | None) -> list[tuple[str, dict]]:
    """Load config file layers in cascade order."""
    layers: list[tuple[str, dict]] = []

    if repo_root is not None:
        cfg = _load_yaml(repo_root / "config" / "config.yml")
        if cfg:
            layers.append(("repo config", cfg))

    user_cfg = _load_yaml(Path.home() / ".signalpilot" / "config.yml")
    if user_cfg:
        layers.append(("user config", user_cfg))

    project_cfg = _load_yaml(Path.cwd() / ".signalpilot" / "config.yml")
    if project_cfg:
        layers.append(("project config", project_cfg))

    return layers


def load_config(repo_root: Path | None = None) -> dict:
    config = copy.deepcopy(_DEFAULTS)

    for _label, layer in _load_layers(repo_root):
        config = _deep_merge(config, layer)

    config = _apply_env(config)
    return config


def resolve_with_sources(repo_root: Path | None = None) -> dict[str, tuple]:
    # Seed with defaults
    result: dict[str, tuple] = {}
    for section, values in _DEFAULTS.items():
        if isinstance(values, dict):
            for key, val in values.items():
                result[f"{section}.{key}"] = (val, "default")

    # Apply file layers in order
    for label, layer in _load_layers(repo_root):
        for section, values in layer.items():
            if isinstance(values, dict):
                for key, val in values.items():
                    flat_key = f"{section}.{key}"
                    if flat_key in result:
                        result[flat_key] = (val, label)

    # Apply env overrides (uses same parser as load_config)
    for section, key, value in _parse_env_overrides(_DEFAULTS):
        flat_key = f"{section}.{key}"
        if flat_key in result:
            result[flat_key] = (value, "env")

    return result
