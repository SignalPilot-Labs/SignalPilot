import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from gateway.dashboard.domain import (
    DashboardDefinition,
    dashboard_content_hash,
    normalize_dashboard_definition,
)

FIXTURE = Path(__file__).parents[2] / "web/dashboard/lightdash-contract/fixtures/five-components.json"


def fixture_definition() -> dict:
    fixture = json.loads(FIXTURE.read_text())
    return {
        "schemaVersion": 1,
        "name": fixture["dashboard"]["name"],
        "description": fixture["dashboard"]["description"],
        "filters": fixture["dashboard"]["filters"],
        "tiles": fixture["dashboard"]["tiles"],
        "charts": fixture["charts"],
        "signalPilot": fixture["signalPilot"],
    }


def test_validates_shared_five_component_fixture_and_hashes_deterministically() -> None:
    source = fixture_definition()
    parsed = DashboardDefinition.model_validate(source)

    assert {chart.visualization.type for chart in parsed.charts} == {
        "big_number",
        "table",
        "cartesian",
    }
    assert dashboard_content_hash(source) == dashboard_content_hash(json.loads(json.dumps(source, sort_keys=True)))
    assert dashboard_content_hash(source) == ("cb77d795b8bdbc9e868a4c8edaa2a73657ae71afe26af213a023cff717cec11f")
    assert normalize_dashboard_definition(parsed)["schemaVersion"] == 1


def test_rejects_renderer_options_and_invalid_semantic_references() -> None:
    source = fixture_definition()
    source["charts"][2]["visualization"]["config"]["eChartsConfig"] = {}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DashboardDefinition.model_validate(source)

    source = fixture_definition()
    source["charts"][0]["visualization"]["config"]["field"] = "orders.missing"
    with pytest.raises(ValidationError, match="unknown query fields"):
        DashboardDefinition.model_validate(source)
