"""Tests for connection health monitoring (Feature #31)."""

import time

import pytest

from signalpilot.gateway.gateway.connectors.health_monitor import (
    ConnectionHealth,
    HealthMonitor,
)


class TestConnectionHealth:
    def test_initial_stats_unknown(self):
        h = ConnectionHealth(connection_name="test", db_type="postgres")
        stats = h.stats()
        assert stats["status"] == "unknown"
        assert stats["sample_count"] == 0

    def test_record_success(self):
        h = ConnectionHealth(connection_name="test", db_type="postgres")
        h.record_event(15.0, True)
        stats = h.stats()
        assert stats["status"] == "healthy"
        assert stats["sample_count"] == 1
        assert stats["successes"] == 1
        assert stats["failures"] == 0
        assert stats["latency_p50_ms"] == 15.0

    def test_record_failure(self):
        h = ConnectionHealth(connection_name="test", db_type="postgres")
        h.record_event(100.0, False, "connection refused")
        stats = h.stats()
        assert stats["failures"] == 1
        assert stats["error_rate"] == 1.0
        assert stats["last_error"] == "connection refused"

    def test_consecutive_failures_unhealthy(self):
        h = ConnectionHealth(connection_name="test", db_type="postgres")
        h.record_event(1.0, False, "err1")
        h.record_event(1.0, False, "err2")
        h.record_event(1.0, False, "err3")
        stats = h.stats()
        assert stats["status"] == "unhealthy"
        assert stats["consecutive_failures"] == 3

    def test_success_resets_consecutive_failures(self):
        h = ConnectionHealth(connection_name="test", db_type="postgres")
        h.record_event(1.0, False, "err")
        h.record_event(1.0, False, "err")
        h.record_event(1.0, True)
        assert h.consecutive_failures == 0
        stats = h.stats()
        assert stats["status"] != "unhealthy"

    def test_high_error_rate_degraded(self):
        h = ConnectionHealth(connection_name="test", db_type="postgres")
        # 6 failures, 4 successes = 60% error rate
        for _ in range(4):
            h.record_event(10.0, True)
        for _ in range(6):
            h.record_event(10.0, False, "err")
        # Reset consecutive by adding a success
        h.record_event(10.0, True)
        stats = h.stats()
        # 6 failures out of 11 = ~54% error rate
        assert stats["status"] == "degraded"

    def test_percentiles(self):
        h = ConnectionHealth(connection_name="test", db_type="postgres")
        for ms in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            h.record_event(float(ms), True)
        stats = h.stats()
        assert stats["latency_p50_ms"] is not None
        assert stats["latency_p95_ms"] is not None
        assert stats["latency_p99_ms"] is not None
        assert stats["latency_avg_ms"] == 55.0
        # p50 should be around 50-55
        assert 45 <= stats["latency_p50_ms"] <= 60

    def test_window_filtering(self):
        h = ConnectionHealth(connection_name="test", db_type="postgres")
        # Add an old event (simulate by manipulating the deque)
        from signalpilot.gateway.gateway.connectors.health_monitor import HealthEvent
        h.events.append(HealthEvent(timestamp=time.time() - 600, latency_ms=999, success=True))
        h.record_event(10.0, True)
        stats = h.stats(window_seconds=300)
        assert stats["sample_count"] == 1  # old event excluded
        assert stats["latency_avg_ms"] == 10.0


class TestHealthMonitor:
    def test_get_or_create(self):
        m = HealthMonitor()
        h1 = m.get_or_create("conn1", "postgres")
        h2 = m.get_or_create("conn1", "postgres")
        assert h1 is h2

    def test_record(self):
        m = HealthMonitor()
        m.record("conn1", 25.0, True, db_type="postgres")
        stats = m.connection_stats("conn1")
        assert stats is not None
        assert stats["sample_count"] == 1

    def test_all_stats(self):
        m = HealthMonitor()
        m.record("conn1", 10.0, True, db_type="postgres")
        m.record("conn2", 20.0, True, db_type="duckdb")
        all_stats = m.all_stats()
        assert len(all_stats) == 2

    def test_connection_stats_missing(self):
        m = HealthMonitor()
        assert m.connection_stats("nonexistent") is None

    def test_remove(self):
        m = HealthMonitor()
        m.record("conn1", 10.0, True)
        m.remove("conn1")
        assert m.connection_stats("conn1") is None
