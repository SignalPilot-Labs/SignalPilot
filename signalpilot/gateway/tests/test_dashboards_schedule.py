"""Refresh timing, spec helpers, dataset parsing, and reference rules."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from gateway.dashboards import checks, datasets, schema
from gateway.dashboards.schedule import compute_next_refresh_at
from tests.dashboards_support import spec_json

NY = ZoneInfo("America/New_York")


def _local(zone: ZoneInfo, *args: int) -> datetime:
    return datetime(*args, tzinfo=zone)


class TestComputeNextRefreshAt:
    def test_off_when_interval_is_none(self) -> None:
        assert compute_next_refresh_at(datetime.now(UTC), None, "06:00", "UTC") is None

    def test_daily_before_anchor_fires_today(self) -> None:
        now = _local(NY, 2026, 9, 8, 5, 0)
        result = compute_next_refresh_at(now, 1440, "06:00", "America/New_York")
        assert result == _local(NY, 2026, 9, 8, 6, 0).astimezone(UTC)
        assert result.tzinfo is UTC

    def test_daily_after_anchor_fires_tomorrow(self) -> None:
        now = _local(NY, 2026, 9, 8, 7, 0)
        result = compute_next_refresh_at(now, 1440, "06:00", "America/New_York")
        assert result == _local(NY, 2026, 9, 9, 6, 0).astimezone(UTC)

    def test_daily_exactly_at_anchor_fires_tomorrow(self) -> None:
        now = _local(NY, 2026, 9, 8, 6, 0)
        result = compute_next_refresh_at(now, 1440, "06:00", "America/New_York")
        assert result == _local(NY, 2026, 9, 9, 6, 0).astimezone(UTC)

    def test_fifteen_minute_alignment(self) -> None:
        now = datetime(2026, 9, 8, 10, 7, tzinfo=UTC)
        result = compute_next_refresh_at(now, 15, "06:00", "UTC")
        assert result == datetime(2026, 9, 8, 10, 15, tzinfo=UTC)

    def test_eight_hour_alignment_to_anchor(self) -> None:
        # Anchor 06:00 -> candidates 22:00, 06:00, 14:00 local.
        now = _local(NY, 2026, 9, 8, 15, 30)
        result = compute_next_refresh_at(now, 480, "06:00", "America/New_York")
        assert result == _local(NY, 2026, 9, 8, 22, 0).astimezone(UTC)

    def test_eight_hour_alignment_before_anchor(self) -> None:
        now = _local(NY, 2026, 9, 8, 1, 0)
        result = compute_next_refresh_at(now, 480, "06:00", "America/New_York")
        assert result == _local(NY, 2026, 9, 8, 6, 0).astimezone(UTC)

    def test_timezone_change_moves_the_instant(self) -> None:
        now = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)
        utc_result = compute_next_refresh_at(now, 1440, "06:00", "UTC")
        ny_result = compute_next_refresh_at(now, 1440, "06:00", "America/New_York")
        assert utc_result == datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
        assert ny_result == datetime(2026, 9, 8, 10, 0, tzinfo=UTC)

    def test_dst_spring_forward_keeps_local_anchor(self) -> None:
        # 2026-03-08 02:00 local does not exist; the 06:00 anchor is unaffected
        # but the UTC offset changes from -5 to -4 across the day.
        now = _local(NY, 2026, 3, 7, 7, 0)
        result = compute_next_refresh_at(now, 1440, "06:00", "America/New_York")
        assert result == datetime(2026, 3, 8, 10, 0, tzinfo=UTC)

    def test_unknown_timezone_falls_back_to_utc(self) -> None:
        now = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)
        assert compute_next_refresh_at(now, 1440, "06:00", "Mars/Olympus") == datetime(2026, 9, 8, 6, 0, tzinfo=UTC)

    def test_naive_now_is_utc(self) -> None:
        result = compute_next_refresh_at(datetime(2026, 9, 8, 5, 0), 60, "06:00", "UTC")
        assert result == datetime(2026, 9, 8, 6, 0, tzinfo=UTC)


class TestSchema:
    def test_valid_spec_has_no_errors(self) -> None:
        assert schema.validate_spec(spec_json()) == []

    def test_invalid_spec_reports_path(self) -> None:
        spec = spec_json()
        spec["charts"][0]["type"] = "hexbin"
        errors = schema.validate_spec(spec)
        assert errors and errors[0].startswith("charts/0")

    def test_dataset_shapes(self) -> None:
        spec = spec_json()
        assert schema.dataset_sql(spec) == {
            "monthly": ("warehouse", "select month, revenue from m"),
            "regions": ("warehouse", "select region, total from r"),
        }
        assert schema.dataset_file_refs(spec) == {
            "monthly": "artifacts/datasets/monthly.csv",
            "regions": "artifacts/datasets/regions.csv",
        }
        assert schema.static_rows(spec["datasets"]["inline"]) == [{"k": "a", "v": 1}]
        assert schema.static_rows(spec["datasets"]["monthly"]) is None
        assert schema.chart_count(spec) == 3

    def test_dataset_must_be_sql_or_static(self) -> None:
        spec = spec_json()
        spec["datasets"]["monthly"] = {"file": "artifacts/monthly.csv"}
        assert any(error.startswith("datasets/monthly") for error in schema.validate_spec(spec))
        spec["datasets"]["monthly"] = {"connection": "warehouse", "sql": "select 1", "rows": []}
        assert any(error.startswith("datasets/monthly") for error in schema.validate_spec(spec))
        spec["datasets"]["monthly"] = {"connection": "warehouse"}
        assert any(error.startswith("datasets/monthly") for error in schema.validate_spec(spec))


class TestDatasets:
    def test_csv_coercion(self) -> None:
        rows = datasets.parse_csv("a,b,c\n1,2.5,\nx, ,3\n")
        assert rows == [{"a": 1, "b": 2.5, "c": None}, {"a": "x", "b": None, "c": 3}]

    def test_only_csv_is_parsed(self) -> None:
        assert datasets.parse_dataset_bytes(b'[{"a": 1}]', "x") == []  # a JSON blob is just a header
        with pytest.raises(ValueError):
            datasets.parse_dataset_bytes(b"\xff\xfe", "x")

    def test_csv_round_trip(self) -> None:
        data = datasets.rows_to_csv(["d", "n", "s"], [{"d": datetime(2026, 1, 1, tzinfo=UTC), "n": None, "s": "q,x"}])
        assert data == b'd,n,s\n2026-01-01T00:00:00+00:00,,"q,x"\n'
        assert datasets.parse_dataset_bytes(data, "r") == [{"d": "2026-01-01T00:00:00+00:00", "n": None, "s": "q,x"}]

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("artifacts/x.csv", "artifacts/x.csv"),
            ("/tmp/signalpilot-chat-runs/run-1/artifacts/x.csv", "artifacts/x.csv"),
            ("/home/user/proj/artifacts/x.csv", "artifacts/x.csv"),
            ("./artifacts/x.csv?raw=1", "artifacts/x.csv"),
            ("https://example.com/x.csv", None),
            ("", None),
        ],
    )
    def test_normalize_file_ref(self, value: str, expected: str | None) -> None:
        assert datasets.normalize_file_ref(value) == expected

    def test_is_artifact_ref(self) -> None:
        assert datasets.is_artifact_ref("artifacts/x.csv")
        assert not datasets.is_artifact_ref("x.csv")
        assert not datasets.is_artifact_ref("artifacts/../x.csv")


class TestChecks:
    def test_missing_column_fails_chart(self) -> None:
        result = checks.check_spec(spec_json(), {"monthly": [{"month": "2026-01-01"}], "regions": [{"region": "n", "total": 1}], "inline": [{"k": "a", "v": 1}]})
        failed = {chart.id for chart in result.failed_charts}
        assert failed == {"rev_line"}
        assert "revenue" in result.failure_messages()[0]

    def test_empty_dataset_is_a_warning(self) -> None:
        result = checks.check_spec(spec_json(), {"monthly": [], "regions": [{"region": "n", "total": 1}], "inline": [{"k": "a", "v": 1}]})
        assert result.ok
        assert result.charts[0].issues[0]["code"] == "empty_dataset"

    def test_unreadable_dataset_fails(self) -> None:
        result = checks.check_spec(spec_json(), {"monthly": None, "regions": [], "inline": []})
        assert not result.ok
