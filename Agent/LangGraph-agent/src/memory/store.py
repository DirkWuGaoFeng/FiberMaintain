"""
Long-term memory store backed by SQLite (async via aiosqlite).

Stores fiber metric snapshots with color-change-only write policy.
90-day lifecycle with automatic cleanup.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite

from .schemas import FiberSnapshot

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("MEMORY_DB", "data/memory.db")


class MemoryStore:
    """Async SQLite-backed long-term memory store."""

    def __init__(self, db_path: str = ""):
        self.db_path = db_path or DB_PATH
        self._initialized = False

    async def _ensure_db(self) -> aiosqlite.Connection:
        """Ensure database exists and schema is created."""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        db = await aiosqlite.connect(self.db_path)
        if not self._initialized:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS fiber_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fiber_id TEXT NOT NULL,
                    spanloss REAL NOT NULL,
                    color TEXT NOT NULL,
                    summary TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_fiber_id ON fiber_snapshots(fiber_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at ON fiber_snapshots(created_at)
            """)
            await db.commit()
            self._initialized = True
        return db

    async def save(self, fiber_id: str, spanloss: float, color: str, summary: str = "") -> None:
        """Save a fiber metric snapshot."""
        db = await self._ensure_db()
        try:
            await db.execute(
                "INSERT INTO fiber_snapshots (fiber_id, spanloss, color, summary) VALUES (?, ?, ?, ?)",
                (fiber_id, spanloss, color, summary),
            )
            await db.commit()
            logger.info(f"[MemoryStore] Saved snapshot: {fiber_id} {color} {spanloss}dB")
        finally:
            await db.close()

    async def get_latest(self, fiber_id: str) -> Optional[dict]:
        """Get the latest snapshot for a fiber."""
        db = await self._ensure_db()
        try:
            cursor = await db.execute(
                "SELECT fiber_id, spanloss, color, summary, created_at FROM fiber_snapshots "
                "WHERE fiber_id = ? ORDER BY created_at DESC LIMIT 1",
                (fiber_id,),
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "fiber_id": row[0],
                    "spanloss": row[1],
                    "color": row[2],
                    "summary": row[3],
                    "created_at": row[4],
                }
            return None
        finally:
            await db.close()

    async def query(self, fiber_id: str, days: int = 30) -> list[dict]:
        """Query historical snapshots for a fiber within the lookback period."""
        db = await self._ensure_db()
        try:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            cursor = await db.execute(
                "SELECT fiber_id, spanloss, color, summary, created_at FROM fiber_snapshots "
                "WHERE fiber_id = ? AND created_at >= ? ORDER BY created_at DESC",
                (fiber_id, cutoff),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "fiber_id": r[0],
                    "spanloss": r[1],
                    "color": r[2],
                    "summary": r[3],
                    "created_at": r[4],
                }
                for r in rows
            ]
        finally:
            await db.close()

    async def cleanup(self, max_age_days: int = 90) -> int:
        """Remove snapshots older than max_age_days. Returns count of deleted rows."""
        db = await self._ensure_db()
        try:
            cutoff = (datetime.utcnow() - timedelta(days=max_age_days)).isoformat()
            cursor = await db.execute(
                "DELETE FROM fiber_snapshots WHERE created_at < ?",
                (cutoff,),
            )
            await db.commit()
            deleted = cursor.rowcount
            if deleted > 0:
                logger.info(f"[MemoryStore] Cleaned up {deleted} old snapshots")
            return deleted
        finally:
            await db.close()


# Module-level singleton
memory_store = MemoryStore()
