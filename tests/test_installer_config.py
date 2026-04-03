import copy
from pathlib import Path
from unittest.mock import patch

import pytest

from signalpilot.gateway.gateway.installer import config as installer_config


# ---------------------------------------------------------------------------
# config._deep_merge()
# ---------------------------------------------------------------------------

class TestDeepMerge:
    """_deep_merge() performs a recursive merge without mutating inputs."""

    def test_flat_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        result = installer_config._deep_merge(base, override)
        assert result == {"a": 1, "b": 99}

    def test_nested_merge(self):
        base = {"gateway": {"host": "0.0.0.0", "port": 3300}}
        override = {"gateway": {"port": 4400}}
        result = installer_config._deep_merge(base, override)
        assert result["gateway"]["port"] == 4400
        assert result["gateway"]["host"] == "0.0.0.0"

    def test_override_with_new_section(self):
        base = {"gateway": {"port": 3300}}
        override = {"newkey": {"nested": True}}
        result = installer_config._deep_merge(base, override)
        assert "gateway" in result
        assert result["newkey"] == {"nested": True}

    def test_no_mutation(self):
        base = {"gateway": {"port": 3300}}
        override = {"gateway": {"port": 4400}}
        base_copy = copy.deepcopy(base)
        override_copy = copy.deepcopy(override)
        installer_config._deep_merge(base, override)
        assert base == base_copy
        assert override == override_copy


# ---------------------------------------------------------------------------
# config._load_yaml()
# ---------------------------------------------------------------------------


class TestLoadYaml:
    """_load_yaml() returns file contents or {} on any failure."""

    def test_valid_file(self, tmp_path):
        yaml_file = tmp_path / "config.yml"
        yaml_file.write_text("gateway:\n  port: 4400\n")
        result = installer_config._load_yaml(yaml_file)
        assert result == {"gateway": {"port": 4400}}

    def test_missing_file(self, tmp_path):
        result = installer_config._load_yaml(tmp_path / "nonexistent.yml")
        assert result == {}

    def test_invalid_yaml(self, tmp_path):
        bad_file = tmp_path / "bad.yml"
        bad_file.write_text("key: [\nnot closed")
        result = installer_config._load_yaml(bad_file)
        assert result == {}


# ---------------------------------------------------------------------------
# config._apply_env()
# ---------------------------------------------------------------------------


class TestApplyEnv:
    """_apply_env() reads SP_* env vars into config, respecting known keys."""

    def test_known_key_override(self, monkeypatch):
        monkeypatch.setenv("SP_GATEWAY_PORT", "9999")
        cfg = {"gateway": {"port": 3300, "host": "0.0.0.0"}}
        result = installer_config._apply_env(cfg)
        assert result["gateway"]["port"] == 9999

    def test_unknown_section_ignored(self, monkeypatch):
        monkeypatch.setenv("SP_UNKNOWN_KEY", "val")
        cfg = {"gateway": {"port": 3300}}
        result = installer_config._apply_env(cfg)
        assert "unknown" not in result
        assert result == {"gateway": {"port": 3300}}

    def test_unknown_key_ignored(self, monkeypatch):
        monkeypatch.setenv("SP_GATEWAY_UNKNOWN", "val")
        cfg = {"gateway": {"port": 3300}}
        result = installer_config._apply_env(cfg)
        assert "unknown" not in result["gateway"]
        assert result["gateway"] == {"port": 3300}

    def test_int_coercion(self, monkeypatch):
        monkeypatch.setenv("SP_DATABASE_PORT", "1234")
        cfg = {"database": {"port": 5600, "host": "localhost"}}
        result = installer_config._apply_env(cfg)
        assert result["database"]["port"] == 1234
        assert isinstance(result["database"]["port"], int)


# ---------------------------------------------------------------------------
# config.load_config()
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """load_config() cascades defaults → repo config → user config → project config → env."""

    def test_defaults_only(self, tmp_path, monkeypatch):
        # Prevent user/project config files from being picked up
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        result = installer_config.load_config(None)
        assert result["gateway"]["port"] == 3300
        assert result["web"]["port"] == 3200
        assert result["database"]["port"] == 5600

    def test_repo_config_merge(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text("gateway:\n  port: 4400\n")
        result = installer_config.load_config(tmp_path)
        assert result["gateway"]["port"] == 4400
        # Other defaults must still be present
        assert result["web"]["port"] == 3200
        assert result["gateway"]["host"] == "0.0.0.0"

    def test_env_overrides_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text("gateway:\n  port: 4400\n")
        monkeypatch.setenv("SP_GATEWAY_PORT", "5500")
        result = installer_config.load_config(tmp_path)
        assert result["gateway"]["port"] == 5500


# ---------------------------------------------------------------------------
# config.resolve_with_sources()
# ---------------------------------------------------------------------------


class TestResolveWithSources:
    """resolve_with_sources() returns a flat dict of (value, source_label) pairs."""

    def test_defaults_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        result = installer_config.resolve_with_sources(None)
        for flat_key, (val, source) in result.items():
            assert source == "default", f"{flat_key} expected 'default', got '{source}'"

    def test_file_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text("gateway:\n  port: 4400\n")
        result = installer_config.resolve_with_sources(tmp_path)
        assert result["gateway.port"] == (4400, "repo config")
        # Key not in repo config stays default
        assert result["web.port"][1] == "default"

    def test_env_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SP_WEB_PORT", "9200")
        result = installer_config.resolve_with_sources(None)
        val, source = result["web.port"]
        assert val == 9200
        assert source == "env"
