"""Connection health monitoring — Feature #31 from the feature table.

Tracks per-connection latency percentiles, error rates, and pool utilization.
Exposes stats via API for dashboard and alerting.

DB-backed: events are buffered in-memory and flushed to gateway_health_events
every 5 seconds. ConnectionHealth state is kept as an in-memory write-through
cache (fast reads) with DB persistence for restart survival.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from sqlalchemy import delete, select, update

logger = logging.getLogger(__name__)


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
            self.events.append(
                HealthEvent(
                    timestamp=time.time(),
                    latency_ms=latency_ms,
                    success=success,
                    error=error,
                )
            )
            self.last_check = time.time()
            if success:
                self.consecutive_failures = 0
                self.last_error = None
            else:
                self.consecutive_failures += 1
                self.last_error = error

    def history(self, window_seconds: int = 3600, bucket_seconds: int = 60) -> list[dict[str, Any]]:
        """Return time-bucketed health history for charting.

        Each bucket contains: timestamp, avg latency, success count, error count.
        Designed for sparkline/chart rendering in the connections UI.
        """
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            recent = [e for e in self.events if e.timestamp > cutoff]

        if not recent:
            return []

        # Create time buckets
        num_buckets = max(1, window_seconds // bucket_seconds)
        buckets: list[dict[str, Any]] = []
        for i in range(num_buckets):
            bucket_start = cutoff + i * bucket_seconds
            bucket_end = bucket_start + bucket_seconds
            bucket_events = [e for e in recent if bucket_start <= e.timestamp < bucket_end]
            if bucket_events:
                latencies = [e.latency_ms for e in bucket_events if e.success]
                buckets.append(
                    {
                        "timestamp": round(bucket_start, 1),
                        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
                        "max_latency_ms": round(max(latencies), 2) if latencies else None,
                        "successes": sum(1 for e in bucket_events if e.success),
                        "failures": sum(1 for e in bucket_events if not e.success),
                        "total": len(bucket_events),
                    }
                )
            else:
                buckets.append(
                    {
                        "timestamp": round(bucket_start, 1),
                        "avg_latency_ms": None,
                        "max_latency_ms": None,
                        "successes": 0,
                        "failures": 0,
                        "total": 0,
                    }
                )
        return buckets

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
    """Global registry of per-connection health stats, org-scoped.

    Keys are "{org_id}::{connection_name}" to prevent cross-org data leakage.

    DB-backed: events are buffered in-memory and batch-flushed to the
    gateway_health_events table. ConnectionHealth state (last_check, last_error,
    consecutive_failures) is synced to gateway_connections columns.
    """

    def __init__(self) -> None:
        self._connections: dict[str, ConnectionHealth] = {}
        self._lock = Lock()
        # Pending events to flush to DB: list of (org_id, conn_name, event)
        self._pending_events: list[tuple[str, str, HealthEvent]] = []
        self._pending_lock = Lock()
        # Track connections with changed health state for DB sync
        self._dirty_connections: set[str] = set()  # keys like "org_id::conn_name"

    @staticmethod
    def _key(connection_name: str) -> str:
        from ..governance.context import require_org_id

        org_id = require_org_id()
        return f"{org_id}::{connection_name}"

    def get_or_create(self, connection_name: str, db_type: str = "unknown") -> ConnectionHealth:
        """Get or create a health tracker for a connection."""
        key = self._key(connection_name)
        with self._lock:
            if key not in self._connections:
                self._connections[key] = ConnectionHealth(
                    connection_name=connection_name,
                    db_type=db_type,
                )
            return self._connections[key]

    def record(
        self,
        connection_name: str,
        latency_ms: float,
        success: bool,
        error: str | None = None,
        db_type: str = "unknown",
    ) -> None:
        """Record an event for a connection."""
        from ..governance.context import require_org_id

        org_id = require_org_id()

        health = self.get_or_create(connection_name, db_type)
        health.record_event(latency_ms, success, error)

        # Buffer event for DB flush
        event = HealthEvent(
            timestamp=time.time(),
            latency_ms=latency_ms,
            success=success,
            error=error,
        )
        key = f"{org_id}::{connection_name}"
        with self._pending_lock:
            self._pending_events.append((org_id, connection_name, event))
            self._dirty_connections.add(key)

    def all_stats(self, window_seconds: int = 300) -> list[dict[str, Any]]:
        """Get stats for all monitored connections in the current org."""
        from ..governance.context import require_org_id

        org_id = require_org_id()
        prefix = f"{org_id}::"
        with self._lock:
            connections = [v for k, v in self._connections.items() if k.startswith(prefix)]
        return [c.stats(window_seconds) for c in connections]

    def connection_stats(self, connection_name: str, window_seconds: int = 300) -> dict[str, Any] | None:
        """Get stats for a specific connection."""
        key = self._key(connection_name)
        with self._lock:
            health = self._connections.get(key)
        if health is None:
            return None
        return health.stats(window_seconds)

    def connection_history(
        self,
        connection_name: str,
        window_seconds: int = 3600,
        bucket_seconds: int = 60,
    ) -> list[dict[str, Any]] | None:
        """Get time-bucketed health history for a connection (for charts).

        Uses in-memory cache for recent data. For full historical data across
        restarts, use connection_history_from_db().
        """
        key = self._key(connection_name)
        with self._lock:
            health = self._connections.get(key)
        if health is None:
            return None
        return health.history(window_seconds, bucket_seconds)

    async def connection_history_from_db(
        self,
        connection_name: str,
        window_seconds: int = 3600,
        bucket_seconds: int = 60,
    ) -> list[dict[str, Any]]:
        """Get time-bucketed health history from DB (survives restarts)."""
        from ..db.engine import get_session_factory
        from ..db.models import GatewayHealthEvent
        from ..governance.context import require_org_id

        org_id = require_org_id()
        cutoff = time.time() - window_seconds
        now = time.time()

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(GatewayHealthEvent)
                .where(
                    GatewayHealthEvent.org_id == org_id,
                    GatewayHealthEvent.connection_name == connection_name,
                    GatewayHealthEvent.timestamp > cutoff,
                )
                .order_by(GatewayHealthEvent.timestamp)
            )
            rows = result.scalars().all()

        if not rows:
            return []

        num_buckets = max(1, window_seconds // bucket_seconds)
        buckets: list[dict[str, Any]] = []
        for i in range(num_buckets):
            bucket_start = cutoff + i * bucket_seconds
            bucket_end = bucket_start + bucket_seconds
            bucket_rows = [r for r in rows if bucket_start <= r.timestamp < bucket_end]
            if bucket_rows:
                latencies = [r.latency_ms for r in bucket_rows if r.success]
                buckets.append(
                    {
                        "timestamp": round(bucket_start, 1),
                        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
                        "max_latency_ms": round(max(latencies), 2) if latencies else None,
                        "successes": sum(1 for r in bucket_rows if r.success),
                        "failures": sum(1 for r in bucket_rows if not r.success),
                        "total": len(bucket_rows),
                    }
                )
            else:
                buckets.append(
                    {
                        "timestamp": round(bucket_start, 1),
                        "avg_latency_ms": None,
                        "max_latency_ms": None,
                        "successes": 0,
                        "failures": 0,
                        "total": 0,
                    }
                )
        return buckets

    def remove(self, connection_name: str) -> None:
        """Remove health tracking for a connection."""
        key = self._key(connection_name)
        with self._lock:
            self._connections.pop(key, None)

    async def flush_to_db(self) -> None:
        """Batch-insert pending events to DB and sync connection health state."""
        from ..db.engine import get_session_factory
        from ..db.models import GatewayConnection, GatewayHealthEvent

        # Grab pending events
        with self._pending_lock:
            events = self._pending_events[:]
            self._pending_events.clear()
            dirty = self._dirty_connections.copy()
            self._dirty_connections.clear()

        if not events and not dirty:
            return

        factory = get_session_factory()
        try:
            async with factory() as session:
                # Batch insert health events
                if events:
                    for org_id, conn_name, evt in events:
                        session.add(
                            GatewayHealthEvent(
                                id=str(uuid.uuid4()),
                                org_id=org_id,
                                connection_name=conn_name,
                                timestamp=evt.timestamp,
                                latency_ms=evt.latency_ms,
                                success=evt.success,
                                error=evt.error,
                            )
                        )

                # Sync connection health state columns
                for key in dirty:
                    org_id, conn_name = key.split("::", 1)
                    with self._lock:
                        health = self._connections.get(key)
                    if health is None:
                        continue
                    await session.execute(
                        update(GatewayConnection)
                        .where(
                            GatewayConnection.org_id == org_id,
                            GatewayConnection.name == conn_name,
                        )
                        .values(
                            health_last_check=health.last_check,
                            health_last_error=health.last_error,
                            health_consecutive_failures=health.consecutive_failures,
                        )
                    )

                await session.commit()
                if events:
                    logger.debug("Flushed %d health events to DB", len(events))
        except Exception:
            logger.warning("Failed to flush health events to DB", exc_info=True)

    async def load_from_db(self) -> None:
        """Warm in-memory cache from DB on startup.

        Loads health state from gateway_connections columns and recent events
        from gateway_health_events (last hour).
        """
        from ..db.engine import get_session_factory
        from ..db.models import GatewayConnection, GatewayHealthEvent

        factory = get_session_factory()
        cutoff = time.time() - 3600  # last hour of events

        try:
            async with factory() as session:
                # Load connection health state
                result = await session.execute(
                    select(GatewayConnection).where(GatewayConnection.health_last_check.isnot(None))
                )
                connections = result.scalars().all()

                for conn in connections:
                    key = f"{conn.org_id}::{conn.name}"
                    health = ConnectionHealth(
                        connection_name=conn.name,
                        db_type=conn.db_type,
                        last_check=conn.health_last_check,
                        last_error=conn.health_last_error,
                        consecutive_failures=conn.health_consecutive_failures or 0,
                    )
                    with self._lock:
                        self._connections[key] = health

                # Load recent events into in-memory deques
                result = await session.execute(
                    select(GatewayHealthEvent)
                    .where(GatewayHealthEvent.timestamp > cutoff)
                    .order_by(GatewayHealthEvent.timestamp)
                )
                events = result.scalars().all()

                for evt in events:
                    key = f"{evt.org_id}::{evt.connection_name}"
                    with self._lock:
                        health = self._connections.get(key)
                    if health is None:
                        continue
                    health.events.append(
                        HealthEvent(
                            timestamp=evt.timestamp,
                            latency_ms=evt.latency_ms,
                            success=evt.success,
                            error=evt.error,
                        )
                    )

                loaded_conns = len(connections)
                loaded_events = len(events)
                if loaded_conns or loaded_events:
                    logger.info(
                        "Loaded health state from DB: %d connections, %d recent events",
                        loaded_conns,
                        loaded_events,
                    )
        except Exception:
            logger.warning("Failed to load health state from DB", exc_info=True)

    async def cleanup_old_events(self, max_age_seconds: int = 7 * 86400) -> None:
        """Delete health events older than max_age_seconds from DB."""
        from ..db.engine import get_session_factory
        from ..db.models import GatewayHealthEvent

        cutoff = time.time() - max_age_seconds
        factory = get_session_factory()
        try:
            async with factory() as session:
                result = await session.execute(delete(GatewayHealthEvent).where(GatewayHealthEvent.timestamp < cutoff))
                await session.commit()
                deleted = result.rowcount
                if deleted:
                    logger.info("Cleaned up %d old health events (>%d days)", deleted, max_age_seconds // 86400)
        except Exception:
            logger.warning("Failed to clean up old health events", exc_info=True)


# Global singleton
health_monitor = HealthMonitor()
