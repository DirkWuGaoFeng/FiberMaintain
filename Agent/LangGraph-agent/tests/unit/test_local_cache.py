"""
本地缓存单元测试 [v7.1]。

测试：
- set/get 基本操作
- TTL 过期
- get_with_staleness（L4 降级）
- cleanup_expired
- 命中/未命中统计
- query_keys 模式匹配
"""

import time

import pytest

from src.cache.local_cache import LocalCache


@pytest.fixture
async def cache(tmp_path):
    """创建带独立 DB 的已初始化缓存实例。"""
    c = LocalCache(db_path=str(tmp_path / "test_cache.db"))
    await c.initialize()
    yield c
    await c.close()


class TestCacheBasicOps:
    """基本 set/get 操作。"""

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache):
        """设置值并取回。"""
        await cache.set("key1", {"data": "hello"})
        result = await cache.get("key1")
        assert result == {"data": "hello"}

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, cache):
        """查询不存在的键返回 None。"""
        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_overwrite(self, cache):
        """重复设置相同键会覆盖旧值。"""
        await cache.set("key1", {"v": 1})
        await cache.set("key1", {"v": 2})
        result = await cache.get("key1")
        assert result == {"v": 2}

    @pytest.mark.asyncio
    async def test_set_various_types(self, cache):
        """缓存应能处理不同的 JSON 可序列化类型。"""
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
        """Delete 移除条目。"""
        await cache.set("key1", "value1")
        await cache.delete("key1")
        result = await cache.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, cache):
        """删除不存在的键不应报错。"""
        await cache.delete("nonexistent")  # 不应抛异常


class TestCacheTTL:
    """TTL 过期测试。"""

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, cache):
        """条目在 TTL 后应过期。"""
        await cache.set("short_lived", "data", ttl=1)
        # 可立即访问
        assert await cache.get("short_lived") == "data"
        # 等待过期
        time.sleep(1.1)
        assert await cache.get("short_lived") is None

    @pytest.mark.asyncio
    async def test_long_ttl_not_expired(self, cache):
        """长 TTL 的条目应仍可访问。"""
        await cache.set("long_lived", "data", ttl=3600)
        result = await cache.get("long_lived")
        assert result == "data"

    @pytest.mark.asyncio
    async def test_default_ttl_applied(self, cache):
        """TTL=0 应使用默认值（300s）。"""
        await cache.set("default_ttl", "data", ttl=0)
        # 应可访问（默认 TTL 为 300s）
        result = await cache.get("default_ttl")
        assert result == "data"


class TestCacheStaleness:
    """get_with_staleness 用于 L4 降级。"""

    @pytest.mark.asyncio
    async def test_fresh_data_not_stale(self, cache):
        """新鲜数据应为 stale=False。"""
        await cache.set("key1", {"v": 1}, ttl=300)
        result = await cache.get_with_staleness("key1")
        assert result is not None
        assert result["stale"] is False
        assert result["value"] == {"v": 1}
        assert result["age_seconds"] < 5

    @pytest.mark.asyncio
    async def test_expired_data_is_stale(self, cache):
        """过期数据应为 stale=True 但仍返回。"""
        await cache.set("key1", {"v": 1}, ttl=1)
        time.sleep(1.1)
        result = await cache.get_with_staleness("key1", max_stale_seconds=600)
        assert result is not None
        assert result["stale"] is True
        assert result["value"] == {"v": 1}

    @pytest.mark.asyncio
    async def test_too_stale_returns_none(self, cache):
        """早于 max_stale_seconds 的数据返回 None。"""
        await cache.set("key1", {"v": 1}, ttl=1)
        time.sleep(1.1)
        # max_stale_seconds=0 表示没有任何数据足够新鲜
        result = await cache.get_with_staleness("key1", max_stale_seconds=0)
        assert result is None

    @pytest.mark.asyncio
    async def test_nonexistent_key_returns_none(self, cache):
        """get_with_staleness 对不存在的键返回 None。"""
        result = await cache.get_with_staleness("nonexistent")
        assert result is None


class TestCacheCleanup:
    """清理过期条目。"""

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired(self, cache):
        """cleanup_expired 移除超过 TTL 的条目。"""
        await cache.set("expired1", "a", ttl=1)
        await cache.set("expired2", "b", ttl=1)
        await cache.set("fresh", "c", ttl=3600)

        time.sleep(1.1)
        removed = await cache.cleanup_expired()
        assert removed == 2

        # 新条目仍可访问
        assert await cache.get("fresh") == "c"

    @pytest.mark.asyncio
    async def test_cleanup_no_expired(self, cache):
        """无过期条目时清理应返回 0。"""
        await cache.set("key1", "a", ttl=3600)
        removed = await cache.cleanup_expired()
        assert removed == 0


class TestCacheStats:
    """命中/未命中统计。"""

    @pytest.mark.asyncio
    async def test_stats_initial(self, cache):
        """初始统计应为 0。"""
        stats = await cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_after_operations(self, cache):
        """统计应能跟踪命中与未命中次数。"""
        await cache.set("key1", "value1")
        await cache.get("key1")  # 命中
        await cache.get("key1")  # 命中
        await cache.get("missing")  # 未命中

        stats = await cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert abs(stats["hit_rate"] - 0.667) < 0.01


class TestCacheQueryKeys:
    """键模式查询。"""

    @pytest.mark.asyncio
    async def test_query_all_keys(self, cache):
        """使用 % 查询返回所有键。"""
        await cache.set("fiber:1", "a")
        await cache.set("fiber:2", "b")
        await cache.set("alarm:1", "c")

        keys = await cache.query_keys("%")
        assert len(keys) == 3

    @pytest.mark.asyncio
    async def test_query_pattern_filter(self, cache):
        """带模式的查询会过滤结果。"""
        await cache.set("fiber:1", "a")
        await cache.set("fiber:2", "b")
        await cache.set("alarm:1", "c")

        keys = await cache.query_keys("fiber")
        assert len(keys) == 2
        for k in keys:
            assert "fiber" in k["key"]

    @pytest.mark.asyncio
    async def test_query_keys_shows_expiry_info(self, cache):
        """查询结果包含年龄与过期信息。"""
        await cache.set("key1", "val", ttl=300)
        keys = await cache.query_keys("key1")
        assert len(keys) == 1
        assert "age_seconds" in keys[0]
        assert "ttl" in keys[0]
        assert "expired" in keys[0]
        assert keys[0]["expired"] is False


class TestCacheUninitialized:
    """缓存未初始化时的行为。"""

    @pytest.mark.asyncio
    async def test_get_without_init(self):
        """未初始化缓存上的 get 返回 None。"""
        cache = LocalCache(db_path="/nonexistent/path.db")
        # 不调用 initialize()
        result = await cache.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_without_init(self):
        """未初始化缓存上的 set 不应抛异常。"""
        cache = LocalCache(db_path="/nonexistent/path.db")
        await cache.set("key", "value")  # 不应抛异常
