"""Tests for schema cache (Feature #18)."""

import time
from unittest.mock import patch

import pytest

from signalpilot.gateway.gateway.connectors.schema_cache import SchemaCache, schema_cache


SAMPLE_SCHEMA = {
    "public.users": {
        "schema": "public",
        "name": "users",
        "columns": [
            {"name": "id", "type": "integer", "nullable": False, "primary_key": True},
            {"name": "email", "type": "varchar", "nullable": False},
        ],
    },
    "public.orders": {
        "schema": "public",
        "name": "orders",
        "columns": [
            {"name": "id", "type": "integer", "nullable": False, "primary_key": True},
            {"name": "user_id", "type": "integer", "nullable": False},
            {"name": "total", "type": "numeric", "nullable": True},
        ],
    },
}


class TestSchemaCache:
    """Tests for the SchemaCache class."""

    def test_miss_returns_none(self):
        cache = SchemaCache(ttl_seconds=60)
        assert cache.get("nonexistent") is None

    def test_put_and_get(self):
        cache = SchemaCache(ttl_seconds=60)
        cache.put("my-conn", SAMPLE_SCHEMA)
        result = cache.get("my-conn")
        assert result is not None
        assert len(result) == 2
        assert "public.users" in result
        assert "public.orders" in result

    def test_returns_same_data(self):
        cache = SchemaCache(ttl_seconds=60)
        cache.put("conn-1", SAMPLE_SCHEMA)
        result = cache.get("conn-1")
        assert result["public.users"]["columns"][0]["name"] == "id"
        assert result["public.orders"]["columns"][2]["type"] == "numeric"

    def test_expiration(self):
        cache = SchemaCache(ttl_seconds=0.01)  # 10ms TTL
        cache.put("conn-1", SAMPLE_SCHEMA)
        # Immediately should hit
        assert cache.get("conn-1") is not None
        # Wait for expiration
        time.sleep(0.02)
        assert cache.get("conn-1") is None

    def test_invalidate_specific(self):
        cache = SchemaCache(ttl_seconds=60)
        cache.put("conn-1", SAMPLE_SCHEMA)
        cache.put("conn-2", {"t": {"schema": "public", "name": "t", "columns": []}})

        count = cache.invalidate("conn-1")
        assert count == 1
        assert cache.get("conn-1") is None
        assert cache.get("conn-2") is not None

    def test_invalidate_all(self):
        cache = SchemaCache(ttl_seconds=60)
        cache.put("conn-1", SAMPLE_SCHEMA)
        cache.put("conn-2", SAMPLE_SCHEMA)
        cache.put("conn-3", SAMPLE_SCHEMA)

        count = cache.invalidate()
        assert count == 3
        assert cache.get("conn-1") is None
        assert cache.get("conn-2") is None
        assert cache.get("conn-3") is None

    def test_invalidate_nonexistent(self):
        cache = SchemaCache(ttl_seconds=60)
        count = cache.invalidate("doesnt-exist")
        assert count == 0

    def test_overwrite(self):
        cache = SchemaCache(ttl_seconds=60)
        cache.put("conn-1", SAMPLE_SCHEMA)
        new_schema = {"public.new_table": {"schema": "public", "name": "new_table", "columns": []}}
        cache.put("conn-1", new_schema)
        result = cache.get("conn-1")
        assert "public.new_table" in result
        assert "public.users" not in result

    def test_stats_empty(self):
        cache = SchemaCache(ttl_seconds=60)
        stats = cache.stats()
        assert stats["cached_connections"] == 0
        assert stats["total_entries"] == 0
        assert stats["ttl_seconds"] == 60

    def test_stats_with_entries(self):
        cache = SchemaCache(ttl_seconds=60)
        cache.put("conn-1", SAMPLE_SCHEMA)
        cache.put("conn-2", SAMPLE_SCHEMA)
        stats = cache.stats()
        assert stats["cached_connections"] == 2
        assert stats["total_entries"] == 2

    def test_stats_expired_entries(self):
        cache = SchemaCache(ttl_seconds=0.01)
        cache.put("conn-1", SAMPLE_SCHEMA)
        time.sleep(0.02)
        stats = cache.stats()
        assert stats["cached_connections"] == 0
        # stats() now lazy-purges expired entries, so total_entries == 0
        assert stats["total_entries"] == 0

    def test_multiple_connections_isolated(self):
        cache = SchemaCache(ttl_seconds=60)
        schema_a = {"t1": {"schema": "a", "name": "t1", "columns": []}}
        schema_b = {"t2": {"schema": "b", "name": "t2", "columns": []}}
        cache.put("conn-a", schema_a)
        cache.put("conn-b", schema_b)
        assert "t1" in cache.get("conn-a")
        assert "t2" in cache.get("conn-b")
        assert "t2" not in cache.get("conn-a")

    def test_global_singleton_exists(self):
        """schema_cache singleton should be importable."""
        assert schema_cache is not None
        assert isinstance(schema_cache, SchemaCache)
