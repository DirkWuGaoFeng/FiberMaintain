"""
Local Cache — SQLite-based with TTL [v7.1].

Features:
- aiosqlite for async operations
- TTL-based expiration (default 5min)
- get_with_staleness() for L4 degradation (serve stale data)
- Stats tracking (hit/miss ratio)

Used by:
- Event router (stats_update caching)
- Degradation manager (L4 offline mode)
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
    SQLite-backed local cache with TTL support.

    Provides L4 degradation capability: serve stale data when backend is down.
    """

    def __init__(self, db_path: str = ""):
        self.db_path = db_path or LOCAL_CACHE_DB
        self._db = None
        self._hits = 0
        self._misses = 0

    async def initialize(self) -> None:
        """Initialize the cache database."""
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
        """Get a cache value (returns None if expired or missing)."""
        if not self._db:
            return None

        try:
            cursor = await self._db.execute(
                "SELECT value, created_at, ttl FROM cache WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            if not row:
                self._misses += 1
                return None

            value_str, created_at, ttl = row
            if time.time() - created_at > ttl:
                # Expired
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
        Get value with staleness info (for L4 degradation).

        Returns:
            {"value": Any, "stale": bool, "age_seconds": float} or None
        """
        if not self._db:
            return None

        try:
            cursor = await self._db.execute(
                "SELECT value, created_at, ttl FROM cache WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            if not row:
                return None

            value_str, created_at, ttl = row
            age = time.time() - created_at
            is_stale = age > ttl

            # Don't serve data older than max_stale_seconds
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
        """Set a cache value with TTL."""
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
        """Delete a cache entry."""
        if not self._db:
            return
        try:
            await self._db.execute("DELETE FROM cache WHERE key = ?", (key,))
            await self._db.commit()
        except Exception:
            pass

    async def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        if not self._db:
            return 0
        try:
            now = time.time()
            cursor = await self._db.execute(
                "DELETE FROM cache WHERE (? - created_at) > ttl", (now,)
            )
            await self._db.commit()
            return cursor.rowcount
        except Exception:
            return 0

    async def get_stats(self) -> dict:
        """Get cache statistics."""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
            "db_path": self.db_path,
        }

    async def query_keys(self, pattern: str = "%") -> list[dict]:
        """Query cache keys matching a pattern."""
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
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None


# =============================================================================
# Singleton
# =============================================================================

_cache_instance: Optional[LocalCache] = None


def get_local_cache() -> Optional[LocalCache]:
    """Get the local cache singleton (may be None if not initialized)."""
    return _cache_instance


async def create_local_cache() -> LocalCache:
    """Create and initialize the local cache singleton."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = LocalCache()
        await _cache_instance.initialize()
    return _cache_instance
