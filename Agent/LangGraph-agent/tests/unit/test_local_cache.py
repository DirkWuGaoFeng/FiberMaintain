"""
Unit tests for Local Cache [v7.1].

Tests:
- set/get basic operations
- TTL expiration
- get_with_staleness (L4 degradation)
- cleanup_expired
- Stats tracking (hit/miss)
- query_keys pattern matching
"""

import time

import pytest

from src.cache.local_cache import LocalCache


@pytest.fixture
async def cache(tmp_path):
    """Create an initialized cache instance with isolated DB."""
    c = LocalCache(db_path=str(tmp_path / "test_cache.db"))
    await c.initialize()
    yield c
    await c.close()


class TestCacheBasicOps:
    """Basic set/get operations."""

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache):
        """Set a value and retrieve it."""
        await cache.set("key1", {"data": "hello"})
        result = await cache.get("key1")
        assert result == {"data": "hello"}

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, cache):
        """Get for missing key returns None."""
        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_overwrite(self, cache):
        """Setting same key overwrites previous value."""
        await cache.set("key1", {"v": 1})
        await cache.set("key1", {"v": 2})
        result = await cache.get("key1")
        assert result == {"v": 2}

    @pytest.mark.asyncio
    async def test_set_various_types(self, cache):
        """Cache should handle different JSON-serializable types."""
        await cache.set("str", "hello")
        await cache.set("num", 42)
        await cache.set("list", [1, 2, 3])
        await cache.set("nested", {"a": {"b": [1, 2]}})

        assert await cache.get("str") == "hello"
        assert await cache.get("num") == 42
        assert await cache.get("list") == [1, 2, 3]
        assert await cache.get("nested") == {"a": {"b": [1, 2]}}

    @pytest.mark.asyncio
    async def test_delete(self, cache):
        """Delete removes the entry."""
        await cache.set("key1", "value1")
        await cache.delete("key1")
        result = await cache.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, cache):
        """Deleting non-existent key should not error."""
        await cache.delete("nonexistent")  # Should not raise


class TestCacheTTL:
    """TTL expiration tests."""

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, cache):
        """Entry should expire after TTL."""
        await cache.set("short_lived", "data", ttl=1)
        # Immediately accessible
        assert await cache.get("short_lived") == "data"
        # Wait for expiration
        time.sleep(1.1)
        assert await cache.get("short_lived") is None

    @pytest.mark.asyncio
    async def test_long_ttl_not_expired(self, cache):
        """Entry with long TTL should remain accessible."""
        await cache.set("long_lived", "data", ttl=3600)
        result = await cache.get("long_lived")
        assert result == "data"

    @pytest.mark.asyncio
    async def test_default_ttl_applied(self, cache):
        """TTL=0 should use default (300s)."""
        await cache.set("default_ttl", "data", ttl=0)
        # Should be accessible (default TTL is 300s)
        result = await cache.get("default_ttl")
        assert result == "data"


class TestCacheStaleness:
    """get_with_staleness for L4 degradation."""

    @pytest.mark.asyncio
    async def test_fresh_data_not_stale(self, cache):
        """Fresh data should have stale=False."""
        await cache.set("key1", {"v": 1}, ttl=300)
        result = await cache.get_with_staleness("key1")
        assert result is not None
        assert result["stale"] is False
        assert result["value"] == {"v": 1}
        assert result["age_seconds"] < 5

    @pytest.mark.asyncio
    async def test_expired_data_is_stale(self, cache):
        """Expired data should have stale=True but still returned."""
        await cache.set("key1", {"v": 1}, ttl=1)
        time.sleep(1.1)
        result = await cache.get_with_staleness("key1", max_stale_seconds=600)
        assert result is not None
        assert result["stale"] is True
        assert result["value"] == {"v": 1}

    @pytest.mark.asyncio
    async def test_too_stale_returns_none(self, cache):
        """Data older than max_stale_seconds returns None."""
        await cache.set("key1", {"v": 1}, ttl=1)
        time.sleep(1.1)
        # max_stale_seconds=0 means nothing is fresh enough
        result = await cache.get_with_staleness("key1", max_stale_seconds=0)
        assert result is None

    @pytest.mark.asyncio
    async def test_nonexistent_key_returns_none(self, cache):
        """get_with_staleness for missing key returns None."""
        result = await cache.get_with_staleness("nonexistent")
        assert result is None


class TestCacheCleanup:
    """Cleanup expired entries."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired(self, cache):
        """cleanup_expired removes entries past TTL."""
        await cache.set("expired1", "a", ttl=1)
        await cache.set("expired2", "b", ttl=1)
        await cache.set("fresh", "c", ttl=3600)

        time.sleep(1.1)
        removed = await cache.cleanup_expired()
        assert removed == 2

        # Fresh entry still accessible
        assert await cache.get("fresh") == "c"

    @pytest.mark.asyncio
    async def test_cleanup_no_expired(self, cache):
        """Cleanup with no expired entries returns 0."""
        await cache.set("key1", "a", ttl=3600)
        removed = await cache.cleanup_expired()
        assert removed == 0


class TestCacheStats:
    """Hit/miss statistics."""

    @pytest.mark.asyncio
    async def test_stats_initial(self, cache):
        """Initial stats should be zero."""
        stats = await cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_after_operations(self, cache):
        """Stats should track hits and misses."""
        await cache.set("key1", "value1")
        await cache.get("key1")  # hit
        await cache.get("key1")  # hit
        await cache.get("missing")  # miss

        stats = await cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert abs(stats["hit_rate"] - 0.667) < 0.01


class TestCacheQueryKeys:
    """Key pattern query."""

    @pytest.mark.asyncio
    async def test_query_all_keys(self, cache):
        """Query with % returns all keys."""
        await cache.set("fiber:1", "a")
        await cache.set("fiber:2", "b")
        await cache.set("alarm:1", "c")

        keys = await cache.query_keys("%")
        assert len(keys) == 3

    @pytest.mark.asyncio
    async def test_query_pattern_filter(self, cache):
        """Query with pattern filters results."""
        await cache.set("fiber:1", "a")
        await cache.set("fiber:2", "b")
        await cache.set("alarm:1", "c")

        keys = await cache.query_keys("fiber")
        assert len(keys) == 2
        for k in keys:
            assert "fiber" in k["key"]

    @pytest.mark.asyncio
    async def test_query_keys_shows_expiry_info(self, cache):
        """Query results include age and expiry info."""
        await cache.set("key1", "val", ttl=300)
        keys = await cache.query_keys("key1")
        assert len(keys) == 1
        assert "age_seconds" in keys[0]
        assert "ttl" in keys[0]
        assert "expired" in keys[0]
        assert keys[0]["expired"] is False


class TestCacheUninitialized:
    """Behavior when cache is not initialized."""

    @pytest.mark.asyncio
    async def test_get_without_init(self):
        """Get on uninitialized cache returns None."""
        cache = LocalCache(db_path="/nonexistent/path.db")
        # Don't call initialize()
        result = await cache.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_without_init(self):
        """Set on uninitialized cache should not raise."""
        cache = LocalCache(db_path="/nonexistent/path.db")
        await cache.set("key", "value")  # Should not raise
