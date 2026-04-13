"""Tests for connection health history — time-bucketed latency tracking.

Verifies that HealthMonitor.connection_history() returns correct
time-bucketed data for sparkline/chart rendering in the connections UI.
"""

import time

from signalpilot.gateway.gateway.connectors.health_monitor import (
    ConnectionHealth,
    HealthMonitor,
)


class TestConnectionHealthHistory:
    """Test the history() method on ConnectionHealth."""

    def test_empty_history(self):
        """No events → empty list."""
        ch = ConnectionHealth(connection_name="test", db_type="postgres")
        assert ch.history(window_seconds=300, bucket_seconds=60) == []

    def test_single_event_single_bucket(self):
        """One event produces one non-empty bucket."""
        ch = ConnectionHealth(connection_name="test", db_type="postgres")
        ch.record_event(latency_ms=42.0, success=True)
        buckets = ch.history(window_seconds=60, bucket_seconds=60)
        # Should have exactly 1 bucket
        assert len(buckets) == 1
        b = buckets[0]
        assert b["successes"] == 1
        assert b["failures"] == 0
        assert b["avg_latency_ms"] == 42.0

    def test_failure_event(self):
        """Failed events should count as failures with no latency."""
        ch = ConnectionHealth(connection_name="test", db_type="postgres")
        ch.record_event(latency_ms=100.0, success=False, error="timeout")
        buckets = ch.history(window_seconds=60, bucket_seconds=60)
        assert len(buckets) == 1
        assert buckets[0]["failures"] == 1
        assert buckets[0]["successes"] == 0
        assert buckets[0]["avg_latency_ms"] is None  # No successful latencies

    def test_multiple_events_aggregation(self):
        """Multiple events in the same bucket are aggregated."""
        ch = ConnectionHealth(connection_name="test", db_type="postgres")
        ch.record_event(latency_ms=10.0, success=True)
        ch.record_event(latency_ms=20.0, success=True)
        ch.record_event(latency_ms=30.0, success=True)
        ch.record_event(latency_ms=100.0, success=False, error="err")
        buckets = ch.history(window_seconds=60, bucket_seconds=60)
        assert len(buckets) == 1
        assert buckets[0]["successes"] == 3
        assert buckets[0]["failures"] == 1
        assert buckets[0]["total"] == 4
        assert buckets[0]["avg_latency_ms"] == 20.0  # (10+20+30)/3
        assert buckets[0]["max_latency_ms"] == 30.0

    def test_bucket_count(self):
        """Window / bucket = expected number of buckets."""
        ch = ConnectionHealth(connection_name="test", db_type="postgres")
        ch.record_event(latency_ms=5.0, success=True)
        buckets = ch.history(window_seconds=300, bucket_seconds=60)
        assert len(buckets) == 5

    def test_empty_buckets_have_null_latency(self):
        """Buckets with no events should have null latency values."""
        ch = ConnectionHealth(connection_name="test", db_type="postgres")
        ch.record_event(latency_ms=5.0, success=True)
        buckets = ch.history(window_seconds=300, bucket_seconds=60)
        # Most buckets should be empty
        empty_buckets = [b for b in buckets if b["total"] == 0]
        for b in empty_buckets:
            assert b["avg_latency_ms"] is None
            assert b["max_latency_ms"] is None
            assert b["successes"] == 0
            assert b["failures"] == 0

    def test_bucket_timestamps_increasing(self):
        """Bucket timestamps should be monotonically increasing."""
        ch = ConnectionHealth(connection_name="test", db_type="postgres")
        ch.record_event(latency_ms=5.0, success=True)
        buckets = ch.history(window_seconds=300, bucket_seconds=60)
        timestamps = [b["timestamp"] for b in buckets]
        assert timestamps == sorted(timestamps)


class TestHealthMonitorHistory:
    """Test the connection_history() method on HealthMonitor."""

    def test_unknown_connection_returns_none(self):
        hm = HealthMonitor()
        assert hm.connection_history("nonexistent") is None

    def test_recorded_events_appear_in_history(self):
        hm = HealthMonitor()
        hm.record("db1", latency_ms=15.0, success=True, db_type="postgres")
        hm.record("db1", latency_ms=25.0, success=True, db_type="postgres")
        history = hm.connection_history("db1", window_seconds=60, bucket_seconds=60)
        assert history is not None
        assert len(history) == 1
        assert history[0]["successes"] == 2
        assert history[0]["avg_latency_ms"] == 20.0

    def test_different_connections_independent(self):
        hm = HealthMonitor()
        hm.record("db1", latency_ms=10.0, success=True, db_type="postgres")
        hm.record("db2", latency_ms=50.0, success=False, error="down", db_type="mysql")
        h1 = hm.connection_history("db1", window_seconds=60, bucket_seconds=60)
        h2 = hm.connection_history("db2", window_seconds=60, bucket_seconds=60)
        assert h1[0]["successes"] == 1 and h1[0]["failures"] == 0
        assert h2[0]["successes"] == 0 and h2[0]["failures"] == 1
