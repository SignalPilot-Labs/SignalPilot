"""Connection health monitoring — Feature #31 from the feature table.

Tracks per-connection latency percentiles, error rates, and pool utilization.
Exposes stats via API for dashboard and alerting.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class HealthEvent:
    """A single health check or query event."""
    timestamp: float
    latency_ms: float
    success: bool
    error: str | None = None


@dataclass
class ConnectionHealth:
    """Aggregated health stats for a single connection."""
    connection_name: str
    db_type: str
    events: deque[HealthEvent] = field(default_factory=lambda: deque(maxlen=500))
    _lock: Lock = field(default_factory=Lock)
    last_check: float | None = None
    last_error: str | None = None
    consecutive_failures: int = 0

    def record_event(self, latency_ms: float, success: bool, error: str | None = None) -> None:
        """Record a query or health check event."""
        with self._lock:
            self.events.append(HealthEvent(
                timestamp=time.time(),
                latency_ms=latency_ms,
                success=success,
                error=error,
            ))
            self.last_check = time.time()
            if success:
                self.consecutive_failures = 0
                self.last_error = None
            else:
                self.consecutive_failures += 1
                self.last_error = error

    def stats(self, window_seconds: int = 300) -> dict[str, Any]:
        """Compute health statistics over the recent time window."""
        cutoff = time.time() - window_seconds
        with self._lock:
            recent = [e for e in self.events if e.timestamp > cutoff]

        if not recent:
            return {
                "connection_name": self.connection_name,
                "db_type": self.db_type,
                "status": "unknown",
                "sample_count": 0,
                "window_seconds": window_seconds,
                "last_check": self.last_check,
            }

        successes = sum(1 for e in recent if e.success)
        failures = len(recent) - successes
        error_rate = failures / len(recent) if recent else 0
        latencies = sorted(e.latency_ms for e in recent if e.success)

        # Determine status
        if self.consecutive_failures >= 3:
            status = "unhealthy"
        elif error_rate > 0.5:
            status = "degraded"
        elif error_rate > 0.1:
            status = "warning"
        else:
            status = "healthy"

        def percentile(data: list[float], p: float) -> float | None:
            if not data:
                return None
            k = (len(data) - 1) * (p / 100)
            f = int(k)
            c = f + 1
            if c >= len(data):
                return data[f]
            return data[f] + (k - f) * (data[c] - data[f])

        return {
            "connection_name": self.connection_name,
            "db_type": self.db_type,
            "status": status,
            "sample_count": len(recent),
            "window_seconds": window_seconds,
            "successes": successes,
            "failures": failures,
            "error_rate": round(error_rate, 4),
            "consecutive_failures": self.consecutive_failures,
            "last_check": self.last_check,
            "last_error": self.last_error,
            "latency_p50_ms": round(percentile(latencies, 50), 2) if latencies else None,
            "latency_p95_ms": round(percentile(latencies, 95), 2) if latencies else None,
            "latency_p99_ms": round(percentile(latencies, 99), 2) if latencies else None,
            "latency_avg_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        }


class HealthMonitor:
    """Global registry of per-connection health stats."""

    def __init__(self) -> None:
        self._connections: dict[str, ConnectionHealth] = {}
        self._lock = Lock()

    def get_or_create(self, connection_name: str, db_type: str = "unknown") -> ConnectionHealth:
        """Get or create a health tracker for a connection."""
        with self._lock:
            if connection_name not in self._connections:
                self._connections[connection_name] = ConnectionHealth(
                    connection_name=connection_name,
                    db_type=db_type,
                )
            return self._connections[connection_name]

    def record(
        self, connection_name: str, latency_ms: float, success: bool,
        error: str | None = None, db_type: str = "unknown",
    ) -> None:
        """Record an event for a connection."""
        health = self.get_or_create(connection_name, db_type)
        health.record_event(latency_ms, success, error)

    def all_stats(self, window_seconds: int = 300) -> list[dict[str, Any]]:
        """Get stats for all monitored connections."""
        with self._lock:
            connections = list(self._connections.values())
        return [c.stats(window_seconds) for c in connections]

    def connection_stats(self, connection_name: str, window_seconds: int = 300) -> dict[str, Any] | None:
        """Get stats for a specific connection."""
        with self._lock:
            health = self._connections.get(connection_name)
        if health is None:
            return None
        return health.stats(window_seconds)

    def remove(self, connection_name: str) -> None:
        """Remove health tracking for a connection."""
        with self._lock:
            self._connections.pop(connection_name, None)


# Global singleton
health_monitor = HealthMonitor()
