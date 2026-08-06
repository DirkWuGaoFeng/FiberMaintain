"""
Experience Store — fault-handling experience memory [改进清单 P1-A].

SQLite table `analysis_experiences` lives in the same memory.db as
fiber_snapshots (frontend_api.MEMORY_DB). Design constraints:

- Deterministic writes only: analysis_expert persists an experience when
  severity is WARNING/CRITICAL — never via LLM self-invoked tools, to
  keep memory noise out of a "rules first, LLM fallback" system.
- Color-change-style dedup: skip when the latest experience for the same
  fiber already carries the same severity, so repeated alarms don't flood
  the table.
- Retrieval is injected into the analysis prompt, not decided by the LLM.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from ..config import DATA_DIR

logger = logging.getLogger(__name__)

MEMORY_DB = str(DATA_DIR / "memory.db")
MAX_EVIDENCE_CHARS = 1000
MAX_SUMMARY_CHARS = 300


class ExperienceStore:
    """SQLite-backed store for analysis experiences."""

    def __init__(self, db_path: str = MEMORY_DB):
        self._db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fiber_key TEXT NOT NULL,
                severity TEXT NOT NULL,
                conclusion TEXT NOT NULL,
                evidence TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_exp_fiber ON analysis_experiences(fiber_key)"
        )
        return conn

    @staticmethod
    def fiber_key_of(fiber_ids: list | None) -> str:
        """Normalize fiber_ids to a stable key ('' when absent)."""
        if not fiber_ids:
            return ""
        return ",".join(str(f) for f in fiber_ids[:5])

    def save(
        self,
        fiber_key: str,
        severity: str,
        conclusion: str,
        evidence: list | None = None,
    ) -> bool:
        """Persist one experience. Returns False when dedup skips it."""
        if not fiber_key or severity not in ("WARNING", "CRITICAL"):
            return False
        conn = self._conn()
        try:
            latest = self._latest(conn, fiber_key)
            if latest and latest["severity"] == severity:
                logger.debug(
                    f"[Experience] Dedup skip: {fiber_key} already {severity}"
                )
                return False
            conn.execute(
                "INSERT INTO analysis_experiences "
                "(fiber_key, severity, conclusion, evidence, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    fiber_key,
                    severity,
                    conclusion[:MAX_SUMMARY_CHARS],
                    json.dumps(evidence or [], ensure_ascii=False)[:MAX_EVIDENCE_CHARS],
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            logger.info(f"[Experience] Saved {severity} experience for {fiber_key}")
            return True
        finally:
            conn.close()

    def query(self, fiber_key: str, days: int = 90, limit: int = 5) -> list[dict]:
        """Recent experiences for the fiber key (newest first)."""
        if not fiber_key:
            return []
        conn = self._conn()
        try:
            since = (datetime.now() - timedelta(days=days)).isoformat()
            rows = conn.execute(
                "SELECT severity, conclusion, evidence, created_at "
                "FROM analysis_experiences "
                "WHERE fiber_key = ? AND created_at >= ? "
                "ORDER BY created_at DESC LIMIT ?",
                (fiber_key, since, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def latest_severity(self, fiber_key: str) -> Optional[str]:
        """Severity of the newest experience, or None."""
        if not fiber_key:
            return None
        conn = self._conn()
        try:
            latest = self._latest(conn, fiber_key)
            return latest["severity"] if latest else None
        finally:
            conn.close()

    @staticmethod
    def _latest(conn: sqlite3.Connection, fiber_key: str) -> Optional[sqlite3.Row]:
        return conn.execute(
            "SELECT severity FROM analysis_experiences "
            "WHERE fiber_key = ? ORDER BY id DESC LIMIT 1",
            (fiber_key,),
        ).fetchone()


_store: Optional[ExperienceStore] = None


def get_experience_store() -> ExperienceStore:
    """Process-wide singleton experience store."""
    global _store
    if _store is None:
        _store = ExperienceStore()
    return _store
