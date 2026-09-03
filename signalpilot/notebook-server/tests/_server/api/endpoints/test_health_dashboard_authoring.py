from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from signalpilot._server.ai.dashboard_authoring_readiness import (
    dashboard_authoring_readiness,
)

if TYPE_CHECKING:
    from pathlib import Path


def _plugin(root: Path, *, version: str, contract: str) -> None:
    manifest = root / ".claude-plugin" / "plugin.json"
    skill = root / "skills" / "dashboard-authoring" / "SKILL.md"
    manifest.parent.mkdir(parents=True)
    skill.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"version": version}))
    skill.write_text(f"authoring contract {contract}")


def test_health_accepts_the_exact_dashboard_skill_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plugin(tmp_path, version="1.1.0", contract="2026-09-02.1")
    monkeypatch.setenv("SP_AGENT_PLUGIN_PATH", str(tmp_path))
    monkeypatch.setenv("SIGNALPILOT_PLUGIN_VERSION", "1.1.0")

    assert dashboard_authoring_readiness() == (True, None)


@pytest.mark.parametrize(
    ("version", "contract"),
    [("1.0.0", "2026-09-02.1"), ("1.1.0", "2026-01-01.1")],
)
def test_health_rejects_an_outdated_dashboard_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
    contract: str,
) -> None:
    _plugin(tmp_path, version=version, contract=contract)
    monkeypatch.setenv("SP_AGENT_PLUGIN_PATH", str(tmp_path))
    monkeypatch.setenv("SIGNALPILOT_PLUGIN_VERSION", "1.1.0")

    assert dashboard_authoring_readiness() == (
        False,
        "dashboard_authoring_skill_contract_mismatch",
    )


def test_health_rejects_a_missing_dashboard_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SP_AGENT_PLUGIN_PATH", str(tmp_path))

    assert dashboard_authoring_readiness() == (
        False,
        "dashboard_authoring_skill_unavailable",
    )
