"""Tests for query deduplication and caching (Feature #30)."""

import time

import pytest

from signalpilot.gateway.gateway.governance.cache import CacheEntry, QueryCache


class TestCacheEntry:
    def test_not_expired_within_ttl(self):
        entry = CacheEntry(key="k", connection_name="conn", rows=[], tables=[], execution_ms=10, sql_executed="SELECT 1")
        assert not entry.is_expired(300)

    def test_expired_after_ttl(self):
        entry = CacheEntry(
            key="k", connection_name="conn", rows=[], tables=[], execution_ms=10, sql_executed="SELECT 1",
            created_at=time.time() - 400,
        )
        assert entry.is_expired(300)


class TestQueryCache:
    def test_miss_returns_none(self):
        cache = QueryCache()
        result = cache.get("conn", "SELECT 1", 100)
        assert result is None

    def test_put_then_get(self):
        cache = QueryCache()
        rows = [{"id": 1, "name": "Alice"}]
        cache.put("conn", "SELECT * FROM users", 100, rows, ["users"], 42.5, "SELECT * FROM users LIMIT 100")
        result = cache.get("conn", "SELECT * FROM users", 100)
        assert result is not None
        assert result.rows == rows
        assert result.tables == ["users"]
        assert result.execution_ms == 42.5
        assert result.sql_executed == "SELECT * FROM users LIMIT 100"

    def test_cache_hit_increments_count(self):
        cache = QueryCache()
        cache.put("conn", "SELECT 1", 100, [{"x": 1}], [], 1.0, "SELECT 1")
        cache.get("conn", "SELECT 1", 100)
        cache.get("conn", "SELECT 1", 100)
        entry = cache.get("conn", "SELECT 1", 100)
        assert entry is not None
        assert entry.hit_count == 3

    def test_different_sql_is_miss(self):
        cache = QueryCache()
        cache.put("conn", "SELECT 1", 100, [], [], 1.0, "SELECT 1")
        result = cache.get("conn", "SELECT 2", 100)
        assert result is None

    def test_different_connection_is_miss(self):
        cache = QueryCache()
        cache.put("conn_a", "SELECT 1", 100, [], [], 1.0, "SELECT 1")
        result = cache.get("conn_b", "SELECT 1", 100)
        assert result is None

    def test_different_row_limit_is_miss(self):
        cache = QueryCache()
        cache.put("conn", "SELECT 1", 100, [], [], 1.0, "SELECT 1")
        result = cache.get("conn", "SELECT 1", 200)
        assert result is None

    def test_sql_normalization(self):
        """Whitespace and case differences should hit the same cache entry."""
        cache = QueryCache()
        cache.put("conn", "SELECT  *  FROM  users", 100, [{"id": 1}], ["users"], 1.0, "sql")
        # Same query with different whitespace/case
        result = cache.get("conn", "select * from users", 100)
        assert result is not None
        assert result.rows == [{"id": 1}]

    def test_ttl_expiration(self):
        cache = QueryCache(ttl_seconds=1)
        cache.put("conn", "SELECT 1", 100, [], [], 1.0, "SELECT 1")
        assert cache.get("conn", "SELECT 1", 100) is not None
        # Manually expire
        key = cache._make_key("conn", "SELECT 1", 100)
        cache._cache[key].created_at = time.time() - 2
        assert cache.get("conn", "SELECT 1", 100) is None

    def test_lru_eviction(self):
        cache = QueryCache(max_entries=2)
        cache.put("conn", "SELECT 1", 100, [{"a": 1}], [], 1.0, "s1")
        time.sleep(0.01)
        cache.put("conn", "SELECT 2", 100, [{"a": 2}], [], 1.0, "s2")
        time.sleep(0.01)
        # This should evict SELECT 1 (oldest)
        cache.put("conn", "SELECT 3", 100, [{"a": 3}], [], 1.0, "s3")
        assert cache.get("conn", "SELECT 1", 100) is None
        assert cache.get("conn", "SELECT 2", 100) is not None
        assert cache.get("conn", "SELECT 3", 100) is not None

    def test_invalidate_all(self):
        cache = QueryCache()
        cache.put("a", "SELECT 1", 100, [], [], 1.0, "s")
        cache.put("b", "SELECT 2", 100, [], [], 1.0, "s")
        count = cache.invalidate()
        assert count == 2
        assert cache.get("a", "SELECT 1", 100) is None
        assert cache.get("b", "SELECT 2", 100) is None

    def test_invalidate_by_connection(self):
        cache = QueryCache()
        cache.put("a", "SELECT 1", 100, [], [], 1.0, "s")
        cache.put("b", "SELECT 2", 100, [], [], 1.0, "s")
        count = cache.invalidate(connection_name="a")
        assert count == 1
        # Connection "a" should be gone, "b" should remain
        assert cache.get("a", "SELECT 1", 100) is None
        assert cache.get("b", "SELECT 2", 100) is not None

    def test_stats(self):
        cache = QueryCache(max_entries=500, ttl_seconds=120)
        cache.put("conn", "SELECT 1", 100, [], [], 1.0, "s")
        cache.get("conn", "SELECT 1", 100)  # hit
        cache.get("conn", "SELECT 999", 100)  # miss
        stats = cache.stats()
        assert stats["entries"] == 1
        assert stats["max_entries"] == 500
        assert stats["ttl_seconds"] == 120
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_stats_empty(self):
        cache = QueryCache()
        stats = cache.stats()
        assert stats["entries"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0
