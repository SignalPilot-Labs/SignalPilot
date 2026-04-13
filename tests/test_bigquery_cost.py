"""Tests for BigQuery cost control features: maximum_bytes_billed, location, job stats."""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock, PropertyMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))


@pytest.fixture
def mock_bigquery():
    """Mock google-cloud-bigquery for unit tests."""
    mock_bq = MagicMock()
    mock_sa = MagicMock()
    with patch.dict("sys.modules", {
        "google.cloud": MagicMock(),
        "google.cloud.bigquery": mock_bq,
        "google.oauth2": MagicMock(),
        "google.oauth2.service_account": mock_sa,
    }):
        yield mock_bq, mock_sa


class TestBigQueryCostControls:
    def test_maximum_bytes_billed_set_via_extras(self):
        """maximum_bytes_billed from credential_extras should be stored."""
        from gateway.connectors.bigquery import BigQueryConnector
        connector = BigQueryConnector()
        connector.set_credential_extras({
            "maximum_bytes_billed": 10737418240,  # 10GB
            "location": "US",
        })
        assert connector._maximum_bytes_billed == 10737418240
        assert connector._location == "US"

    def test_maximum_bytes_billed_string_conversion(self):
        """String values for maximum_bytes_billed should be converted to int."""
        from gateway.connectors.bigquery import BigQueryConnector
        connector = BigQueryConnector()
        connector.set_credential_extras({
            "maximum_bytes_billed": "5368709120",  # 5GB as string
        })
        assert connector._maximum_bytes_billed == 5368709120

    def test_format_bytes_helper(self):
        """_format_bytes should format bytes into human-readable strings."""
        from gateway.connectors.bigquery import BigQueryConnector
        assert BigQueryConnector._format_bytes(0) == "0.0 B"
        assert BigQueryConnector._format_bytes(1024) == "1.0 KB"
        assert BigQueryConnector._format_bytes(1073741824) == "1.0 GB"
        assert BigQueryConnector._format_bytes(1099511627776) == "1.0 TB"

    def test_last_job_stats_initially_none(self):
        """get_last_job_stats should return None before any query."""
        from gateway.connectors.bigquery import BigQueryConnector
        connector = BigQueryConnector()
        assert connector.get_last_job_stats() is None

    def test_location_set_via_extras_without_credentials(self):
        """Location should be stored even without credentials_json."""
        from gateway.connectors.bigquery import BigQueryConnector
        connector = BigQueryConnector()
        connector._location = ""
        connector.set_credential_extras({
            "location": "europe-west1",
        })
        assert connector._location == "europe-west1"


class TestBigQueryModels:
    def test_connection_create_has_location(self):
        """ConnectionCreate should accept location and maximum_bytes_billed."""
        from gateway.models import ConnectionCreate
        conn = ConnectionCreate(
            name="test-bq",
            db_type="bigquery",
            project="my-project",
            credentials_json='{"type": "service_account"}',
            location="US",
            maximum_bytes_billed=10737418240,
        )
        assert conn.location == "US"
        assert conn.maximum_bytes_billed == 10737418240

    def test_connection_info_has_location(self):
        """ConnectionInfo should include location and maximum_bytes_billed."""
        from gateway.models import ConnectionInfo
        info = ConnectionInfo(
            id="test-id",
            name="test-bq",
            db_type="bigquery",
            project="my-project",
            location="EU",
            maximum_bytes_billed=5368709120,
        )
        assert info.location == "EU"
        assert info.maximum_bytes_billed == 5368709120


class TestCostEstimatorPricing:
    def test_bigquery_pricing_2026(self):
        """BigQuery cost-per-row should reflect 2026 pricing ($6.25/TB)."""
        from gateway.governance.cost_estimator import _COST_PER_ROW
        # $6.25/TB, ~1KB/row = $6.25 / 1B rows = 0.00000625 per row
        assert _COST_PER_ROW["bigquery"] == 0.000_006_25

    def test_credential_extras_extraction(self):
        """BigQuery extras should include location and maximum_bytes_billed."""
        from gateway.store import _extract_credential_extras
        from gateway.models import ConnectionCreate
        conn = ConnectionCreate(
            name="bq-test",
            db_type="bigquery",
            project="my-project",
            credentials_json='{"type": "service_account"}',
            location="us-east1",
            maximum_bytes_billed=1073741824,
        )
        extras = _extract_credential_extras(conn)
        assert extras["location"] == "us-east1"
        assert extras["maximum_bytes_billed"] == 1073741824
        assert extras["project"] == "my-project"
