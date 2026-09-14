"""The gateway's bundled dashboard schema must match the plugin's source of truth."""

from __future__ import annotations

from pathlib import Path

import pytest

from gateway.dashboards import schema

PLUGIN_SCHEMA = Path(__file__).parents[3] / "signalpilot-plugin/skills/dashboard/dashboard.schema.json"


@pytest.mark.skipif(not PLUGIN_SCHEMA.exists(), reason="plugin checkout absent")
def test_bundled_schema_is_byte_identical_to_plugin() -> None:
    assert schema.SCHEMA_PATH.read_bytes() == PLUGIN_SCHEMA.read_bytes()
