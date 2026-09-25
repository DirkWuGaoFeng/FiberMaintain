"""
本地缓存 — 基于 SQLite 并支持 TTL [v7.1]。

特性：
- 使用 aiosqlite 进行异步操作
- 基于 TTL 的过期机制（默认 5 分钟）
- 提供 get_with_staleness() 用于 L4 降级（在后台不可用时返回陈旧数据）
- 统计跟踪（命中/未命中率）

使用方：
- 事件路由器（stats_update 缓存）
- 降级管理器（L4 离线模式）
- internal_tools.cache_query
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from ..config import CACHE_DEFAULT_TTL, LOCAL_CACHE_DB

logger = logging.getLogger(__name__)


class LocalCache:
    """
    基于 SQLite 的本地缓存，支持 TTL。

    提供 L4 降级能力：当后端不可用时返回陈旧数据。
    """

    def __init__(self, db_path: str = ""):
        self.db_path = db_path or LOCAL_CACHE_DB
        self._db = None
        self._hits = 0
        self._misses = 0

    async def initialize(self) -> None:
        """初始化缓存数据库。"""
        try:
            import aiosqlite

            self._db = await aiosqlite.connect(self.db_path)
            await self._db.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    ttl INTEGER NOT NULL
                )
            """)
            await self._db.commit()
            logger.info(f"[LocalCache] Initialized: {self.db_path}")
        except ImportError:
            logger.warning("[LocalCache] aiosqlite not available, cache disabled")
        except Exception as e:
            logger.error(f"[LocalCache] Init failed: {e}")

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存值（已过期或不存在时返回 None）。"""
        if not self._db:
            return None

        try:
            cursor = await self._db.execute("SELECT value, created_at, ttl FROM cache WHERE key = ?", (key,))
            row = await cursor.fetchone()
            if not row:
                self._misses += 1
                return None

            value_str, created_at, ttl = row
            if time.time() - created_at > ttl:
                # 已过期
                self._misses += 1
                await self._db.execute("DELETE FROM cache WHERE key = ?", (key,))
                await self._db.commit()
                return None

            self._hits += 1
            return json.loads(value_str)
        except Exception as e:
            logger.debug(f"[LocalCache] Get error: {e}")
            self._misses += 1
            return None

    async def get_with_staleness(self, key: str, max_stale_seconds: int = 600) -> Optional[dict]:
        """
        获取带过期状态的值（用于 L4 降级）。

        返回值：
            {"value": Any, "stale": bool, "age_seconds": float} 或 None
        """
        if not self._db:
            return None

        try:
            cursor = await self._db.execute("SELECT value, created_at, ttl FROM cache WHERE key = ?", (key,))
            row = await cursor.fetchone()
            if not row:
                return None

            value_str, created_at, ttl = row
            age = time.time() - created_at
            is_stale = age > ttl

            # 不返回超过 max_stale_seconds 的旧数据
            if age > max_stale_seconds:
                return None

            return {
                "value": json.loads(value_str),
                "stale": is_stale,
                "age_seconds": round(age, 1),
            }
        except Exception:
            return None

    async def set(self, key: str, value: Any, ttl: int = 0) -> None:
        """写入缓存值并指定 TTL。"""
        if not self._db:
            return

        ttl = ttl or CACHE_DEFAULT_TTL
        try:
            await self._db.execute(
                "INSERT OR REPLACE INTO cache (key, value, created_at, ttl) VALUES (?, ?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), time.time(), ttl),
            )
            await self._db.commit()
        except Exception as e:
            logger.debug(f"[LocalCache] Set error: {e}")

    async def delete(self, key: str) -> None:
        """删除一条缓存记录。"""
        if not self._db:
            return
        try:
            await self._db.execute("DELETE FROM cache WHERE key = ?", (key,))
            await self._db.commit()
        except Exception:
            pass

    async def cleanup_expired(self) -> int:
        """删除所有已过期的记录。返回删除数量。"""
        if not self._db:
            return 0
        try:
            now = time.time()
            cursor = await self._db.execute("DELETE FROM cache WHERE (? - created_at) > ttl", (now,))
            await self._db.commit()
            return cursor.rowcount
        except Exception:
            return 0

    async def get_stats(self) -> dict:
        """获取缓存统计信息。"""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
            "db_path": self.db_path,
        }

    async def query_keys(self, pattern: str = "%") -> list[dict]:
        """按模式查询缓存键。"""
        if not self._db:
            return []
        try:
            cursor = await self._db.execute(
                "SELECT key, created_at, ttl FROM cache WHERE key LIKE ? LIMIT 20",
                (f"%{pattern}%",),
            )
            rows = await cursor.fetchall()
            now = time.time()
            return [
                {"key": r[0], "age_seconds": round(now - r[1], 1), "ttl": r[2], "expired": now - r[1] > r[2]}
                for r in rows
            ]
        except Exception:
            return []

    async def close(self) -> None:
        """关闭数据库连接。"""
        if self._db:
            await self._db.close()
            self._db = None


# =============================================================================
# 单例
# =============================================================================

_cache_instance: Optional[LocalCache] = None


def get_local_cache() -> Optional[LocalCache]:
    """获取本地缓存单例（未初始化时可能为 None）。"""
    return _cache_instance


async def create_local_cache() -> LocalCache:
    """创建并初始化本地缓存单例。"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = LocalCache()
        await _cache_instance.initialize()
    return _cache_instance
