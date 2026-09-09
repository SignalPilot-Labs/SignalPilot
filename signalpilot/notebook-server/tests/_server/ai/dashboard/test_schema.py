"""Schema location, validation messages, and the shipped example."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from signalpilot._server.ai.dashboard.schema import (
    DashboardSchemaUnavailable,
    _load_validator,
    dataset_file_refs,
    dataset_sql,
    locate_schema_file,
    validate_spec,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
PLUGIN_ROOT = REPO_ROOT / "signalpilot-plugin"
SKILL_DIR = PLUGIN_ROOT / "skills" / "dashboard"
SCHEMA_COPIES = (
    REPO_ROOT / "signalpilot" / "web" / "dashboard-renderer" / "dashboard.schema.json",
    REPO_ROOT / "signalpilot" / "gateway" / "gateway" / "dashboards" / "dashboard.schema.json",
)


@pytest.mark.parametrize("copy", SCHEMA_COPIES, ids=("web", "gateway"))
def test_schema_copies_are_byte_identical_to_the_plugin(copy: Path):
    assert copy.read_bytes() == (SKILL_DIR / "dashboard.schema.json").read_bytes()


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
    sql = dataset_sql(example)
    assert set(sql) == {"monthly", "by_region"}
    assert all(connection == "warehouse" for connection, _ in sql.values())
    assert "sum(" in sql["monthly"][1]
    assert "over (" in sql["monthly"][1]
    assert "case" in sql["by_region"][1]
    assert dataset_file_refs(example) == [
        {"name": "monthly", "path": "artifacts/datasets/monthly.csv"},
        {"name": "by_region", "path": "artifacts/datasets/by_region.csv"},
    ]
    assert list(example["datasets"]["totals"]) == ["rows"]
    for definition in example["datasets"].values():
        assert "file" not in definition
        assert "source" not in definition


def test_dataset_shapes_are_exclusive():
    def errors_for(dataset: dict) -> list[str]:
        return validate_spec(
            {
                "version": 1,
                "title": "T",
                "datasets": {"m": dataset},
                "charts": [
                    {
                        "id": "k",
                        "type": "kpi",
                        "title": "K",
                        "dataset": "m",
                        "value": {"column": "x"},
                    }
                ],
            }
        )

    assert errors_for({"connection": "w", "sql": "select 1"}) == []
    assert errors_for({"rows": [{"x": 1}]}) == []
    assert errors_for({"sql": "select 1"}) != []
    assert errors_for({"connection": "w"}) != []
    assert errors_for({"connection": "w", "sql": ""}) != []
    assert errors_for({"connection": "w", "sql": "select 1", "rows": []}) != []
    assert errors_for({"file": "artifacts/x.csv"}) != []
    assert (
        errors_for(
            {
                "connection": "w",
                "sql": "select 1",
                "source": {"kind": "sql"},
            }
        )
        != []
    )
    assert dataset_sql({"datasets": {"a": {"rows": []}, "b": "junk"}}) == {}


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
    assert "sp.dashboard_dataset(" in text
    assert "artifacts/datasets/<name>.csv" in text
    assert "over (" in text.lower()
    assert "case" in text.lower()
    assert "to_csv" not in text
    assert '"file"' not in text
    assert '"source"' not in text
    assert "—" not in text
    for code in (
        "missing_dataset",
        "snapshot_missing",
        "snapshot_stale",
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


def test_notebook_skill_exists_and_follows_prompt_rules():
    """The notebook skill carries the rules the system prompt no longer inlines."""
    text = (PLUGIN_ROOT / "skills" / "notebook" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: notebook\n")
    assert "—" not in text
    for phrase in (
        "MultipleDefinitionError",
        "fig.savefig(sp.artifact_path(",
        "sp.dashboard_dataset",
        "Write SQL in the dialect of the connection",
        "SP_CHAT_ARTIFACTS_DIRECTORY",
    ):
        assert phrase in text, phrase
