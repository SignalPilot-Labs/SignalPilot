"""Tests for connection health monitoring — Feature #31."""

import time

import pytest

from signalpilot.gateway.gateway.connectors.health_monitor import (
    ConnectionHealth,
    HealthEvent,
    HealthMonitor,
)


class TestConnectionHealth:
    """Tests for ConnectionHealth tracking."""

    def test_initial_stats_unknown(self):
        health = ConnectionHealth(connection_name="test", db_type="postgres")
        stats = health.stats()
        assert stats["status"] == "unknown"
        assert stats["sample_count"] == 0

    def test_healthy_after_success(self):
        health = ConnectionHealth(connection_name="test", db_type="postgres")
        health.record_event(latency_ms=10.0, success=True)
        stats = health.stats()
        assert stats["status"] == "healthy"
        assert stats["successes"] == 1
        assert stats["failures"] == 0
        assert stats["error_rate"] == 0.0

    def test_consecutive_failures_tracked(self):
        health = ConnectionHealth(connection_name="test", db_type="postgres")
        health.record_event(5.0, success=True)
        health.record_event(100.0, success=False, error="timeout")
        health.record_event(100.0, success=False, error="timeout")
        assert health.consecutive_failures == 2
        assert health.last_error == "timeout"

    def test_success_resets_consecutive_failures(self):
        health = ConnectionHealth(connection_name="test", db_type="postgres")
        health.record_event(100.0, success=False, error="error1")
        health.record_event(100.0, success=False, error="error2")
        assert health.consecutive_failures == 2
        health.record_event(5.0, success=True)
        assert health.consecutive_failures == 0
        assert health.last_error is None

    def test_unhealthy_after_3_failures(self):
        health = ConnectionHealth(connection_name="test", db_type="postgres")
        for _ in range(3):
            health.record_event(100.0, success=False, error="fail")
        stats = health.stats()
        assert stats["status"] == "unhealthy"

    def test_degraded_high_error_rate(self):
        health = ConnectionHealth(connection_name="test", db_type="postgres")
        for _ in range(4):
            health.record_event(10.0, success=True)
        for _ in range(6):
            health.record_event(100.0, success=False, error="fail")
        health.consecutive_failures = 0
        stats = health.stats()
        assert stats["status"] == "degraded"

    def test_warning_moderate_error_rate(self):
        health = ConnectionHealth(connection_name="test", db_type="postgres")
        for _ in range(8):
            health.record_event(10.0, success=True)
        for _ in range(2):
            health.record_event(100.0, success=False, error="slow")
        health.consecutive_failures = 0
        stats = health.stats()
        assert stats["status"] == "warning"

    def test_latency_percentiles(self):
        health = ConnectionHealth(connection_name="test", db_type="postgres")
        for i in range(1, 11):
            health.record_event(float(i * 10), success=True)
        stats = health.stats()
        assert stats["latency_p50_ms"] is not None
        assert stats["latency_p95_ms"] is not None
        assert stats["latency_p99_ms"] is not None
        assert stats["latency_avg_ms"] == 55.0

    def test_latency_excludes_failures(self):
        health = ConnectionHealth(connection_name="test", db_type="postgres")
        health.record_event(10.0, success=True)
        health.record_event(5000.0, success=False, error="timeout")
        stats = health.stats()
        assert stats["latency_avg_ms"] == 10.0

    def test_window_filtering(self):
        health = ConnectionHealth(connection_name="test", db_type="postgres")
        old_event = HealthEvent(
            timestamp=time.time() - 600,
            latency_ms=10.0,
            success=True,
        )
        health.events.append(old_event)
        health.record_event(20.0, success=True)
        stats = health.stats(window_seconds=300)
        assert stats["sample_count"] == 1


class TestHealthMonitor:
    """Tests for the HealthMonitor registry."""

    def test_get_or_create(self):
        monitor = HealthMonitor()
        h = monitor.get_or_create("db1", "postgres")
        assert h.connection_name == "db1"
        assert h.db_type == "postgres"

    def test_get_or_create_reuses(self):
        monitor = HealthMonitor()
        h1 = monitor.get_or_create("db1", "postgres")
        h2 = monitor.get_or_create("db1", "postgres")
        assert h1 is h2

    def test_record(self):
        monitor = HealthMonitor()
        monitor.record("db1", 10.0, True, db_type="postgres")
        stats = monitor.connection_stats("db1")
        assert stats is not None
        assert stats["successes"] == 1

    def test_all_stats(self):
        monitor = HealthMonitor()
        monitor.record("db1", 10.0, True, db_type="postgres")
        monitor.record("db2", 20.0, True, db_type="duckdb")
        all_stats = monitor.all_stats()
        assert len(all_stats) == 2

    def test_connection_stats_missing(self):
        monitor = HealthMonitor()
        assert monitor.connection_stats("nonexistent") is None

    def test_remove(self):
        monitor = HealthMonitor()
        monitor.record("db1", 10.0, True)
        monitor.remove("db1")
        assert monitor.connection_stats("db1") is None

    def test_remove_nonexistent_is_noop(self):
        monitor = HealthMonitor()
        monitor.remove("nonexistent")
