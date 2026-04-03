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
    except Exception:
        return {}


def _apply_env(config: dict) -> dict:
    result = copy.deepcopy(config)
    for env_key, env_val in os.environ.items():
        if not env_key.startswith("SP_"):
            continue
        parts = env_key[3:].lower().split("_", 1)
        if len(parts) != 2:
            continue
        section, key = parts
        if section not in result or not isinstance(result[section], dict):
            continue
        if key not in result[section]:
            continue
        default_val = result[section][key]
        if isinstance(default_val, int):
            try:
                result[section][key] = int(env_val)
            except ValueError:
                pass
        else:
            result[section][key] = env_val
    return result


def load_config(repo_root: Path | None = None) -> dict:
    config = copy.deepcopy(_DEFAULTS)

    if repo_root is not None:
        repo_cfg = _load_yaml(repo_root / "config" / "config.yml")
        config = _deep_merge(config, repo_cfg)

    user_cfg = _load_yaml(Path.home() / ".signalpilot" / "config.yml")
    config = _deep_merge(config, user_cfg)

    project_cfg = _load_yaml(Path.cwd() / ".signalpilot" / "config.yml")
    config = _deep_merge(config, project_cfg)

    config = _apply_env(config)

    return config


def resolve_with_sources(repo_root: Path | None = None) -> dict[str, tuple]:
    layers: list[tuple[str, dict]] = [("default", copy.deepcopy(_DEFAULTS))]

    if repo_root is not None:
        repo_cfg = _load_yaml(repo_root / "config" / "config.yml")
        if repo_cfg:
            layers.append(("repo config", repo_cfg))

    user_cfg = _load_yaml(Path.home() / ".signalpilot" / "config.yml")
    if user_cfg:
        layers.append(("user config", user_cfg))

    project_cfg = _load_yaml(Path.cwd() / ".signalpilot" / "config.yml")
    if project_cfg:
        layers.append(("project config", project_cfg))

    # Build a merged config tracking which layer last set each key
    result: dict[str, tuple] = {}

    # Seed with defaults
    for section, values in _DEFAULTS.items():
        if isinstance(values, dict):
            for key, val in values.items():
                result[f"{section}.{key}"] = (val, "default")

    # Apply file layers in order
    for label, layer in layers[1:]:
        for section, values in layer.items():
            if isinstance(values, dict):
                for key, val in values.items():
                    flat_key = f"{section}.{key}"
                    if flat_key in result:
                        result[flat_key] = (val, label)

    # Apply env overrides
    defaults_flat = {f"{s}.{k}": v for s, vals in _DEFAULTS.items() if isinstance(vals, dict) for k, v in vals.items()}
    for env_key, env_val in os.environ.items():
        if not env_key.startswith("SP_"):
            continue
        parts = env_key[3:].lower().split("_", 1)
        if len(parts) != 2:
            continue
        section, key = parts
        flat_key = f"{section}.{key}"
        if flat_key not in result:
            continue
        default_val = defaults_flat.get(flat_key)
        if isinstance(default_val, int):
            try:
                result[flat_key] = (int(env_val), "env")
            except ValueError:
                pass
        else:
            result[flat_key] = (env_val, "env")

    return result
