"""Schema location, validation messages, and the shipped example."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from signalpilot._server.ai.dashboard.schema import (
    DashboardSchemaUnavailable,
    _load_validator,
    locate_schema_file,
    validate_spec,
)

PLUGIN_ROOT = Path(__file__).resolve().parents[6] / "signalpilot-plugin"
SKILL_DIR = PLUGIN_ROOT / "skills" / "dashboard"


def test_schema_is_found_in_the_repo_checkout(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SP_AGENT_PLUGIN_PATH", raising=False)
    assert locate_schema_file() == SKILL_DIR / "dashboard.schema.json"


def test_plugin_path_env_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "skills" / "dashboard" / "dashboard.schema.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        (SKILL_DIR / "dashboard.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setenv("SP_AGENT_PLUGIN_PATH", str(tmp_path))
    assert locate_schema_file() == target


def test_unreadable_schema_raises(tmp_path: Path):
    broken = tmp_path / "dashboard.schema.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(DashboardSchemaUnavailable):
        _load_validator(str(broken))


def test_example_revenue_dashboard_validates():
    example = json.loads(
        (SKILL_DIR / "examples" / "revenue.dashboard.json").read_text(
            encoding="utf-8"
        )
    )
    assert validate_spec(example) == []
    types = {chart["type"] for chart in example["charts"]}
    assert types == {"kpi", "line", "bar", "pie", "table"}
    assert any("series" in chart for chart in example["charts"])
    assert len(example["filters"]) == 2
    files = [d for d in example["datasets"].values() if "file" in d]
    inline = [d for d in example["datasets"].values() if "rows" in d]
    assert len(files) == 2
    assert len(inline) == 1


def test_validation_messages_carry_json_paths():
    errors = validate_spec(
        {
            "version": 1,
            "title": "T",
            "datasets": {"m": {"rows": []}},
            "charts": [
                {
                    "id": "Bad-Id",
                    "type": "kpi",
                    "title": "K",
                    "dataset": "m",
                    "value": {"column": "x"},
                }
            ],
        }
    )
    assert errors
    assert any(error.startswith("$.charts[0]") for error in errors)

    assert validate_spec({"version": 1}) != []
    assert validate_spec("nope") != []
    assert (
        validate_spec(
            {
                "version": 1,
                "title": "T",
                "datasets": {"m": {"rows": [{"x": 1}]}},
                "charts": [
                    {
                        "id": "k",
                        "type": "kpi",
                        "title": "K",
                        "dataset": "m",
                        "value": {"column": "x", "format": "currency:USD"},
                    }
                ],
            }
        )
        == []
    )


def test_skill_document_points_at_the_schema_and_tools():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: dashboard\n")
    assert "dashboard.schema.json" in text
    assert "dashboard_sample_data" in text
    assert "dashboard_screenshot" in text
    assert "—" not in text
    for code in (
        "missing_dataset",
        "dataset_unreadable",
        "missing_column",
        "series_with_multi_y",
        "empty_dataset",
        "non_numeric_y",
        "unparseable_date",
        "too_many_rows",
        "unknown_chart",
    ):
        assert f"`{code}`" in text, code
