"""
用户记忆存储 (UserMemoryStore).

【设计原则】
对应 AI Agent 设计原则 Chapter 3 用户记忆系统：
  - 区分"用户记忆"（个性化偏好）和"知识库"（集体知识）
  - SQLite WAL 模式持久化，支持并发读写
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional

from src.config import USER_MEMORY_DB

logger = logging.getLogger(__name__)


class UserMemoryStore:
    """SQLite 后端用户记忆存储."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or USER_MEMORY_DB
        self._init_db()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_memory (
                    user_id TEXT PRIMARY KEY,
                    preferences TEXT NOT NULL DEFAULT '{}',
                    history TEXT NOT NULL DEFAULT '[]',
                    last_session TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL DEFAULT 0,
                    version INTEGER NOT NULL DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_event_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                )
            """)

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def load(self, user_id: str) -> Optional[dict]:
        """加载用户记忆."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM user_memory WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                return None
            return {
                "user_id": row["user_id"],
                "preferences": json.loads(row["preferences"]),
                "history": json.loads(row["history"]),
                "last_session": row["last_session"],
                "updated_at": row["updated_at"],
                "version": row["version"],
            }

    def save(self, user_id: str, memory: dict) -> None:
        """保存用户记忆（全量覆盖）."""
        now = time.time()
        with self._get_conn() as conn:
            existing = conn.execute("SELECT version FROM user_memory WHERE user_id = ?", (user_id,)).fetchone()
            if existing:
                conn.execute(
                    """UPDATE user_memory
                       SET preferences=?, history=?, last_session=?,
                           updated_at=?, version=version+1
                       WHERE user_id=?""",
                    (
                        json.dumps(memory.get("preferences", {})),
                        json.dumps(memory.get("history", [])),
                        memory.get("last_session", ""),
                        now,
                        user_id,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO user_memory
                       (user_id, preferences, history, last_session,
                        updated_at, version)
                       VALUES (?, ?, ?, ?, ?, 1)""",
                    (
                        user_id,
                        json.dumps(memory.get("preferences", {})),
                        json.dumps(memory.get("history", [])),
                        memory.get("last_session", ""),
                        now,
                    ),
                )

    def update_preferences(self, user_id: str, preferences: dict) -> None:
        """合并更新用户偏好."""
        existing = self.load(user_id)
        if existing:
            merged = {**existing["preferences"], **preferences}
            memory = {**existing, "preferences": merged}
        else:
            memory = {
                "user_id": user_id,
                "preferences": preferences,
                "history": [],
                "last_session": "",
            }
        self.save(user_id, memory)

    def add_history(self, user_id: str, event: dict) -> None:
        """追加历史事件."""
        existing = self.load(user_id)
        if existing:
            history = existing["history"]
            history.append(event)
            # 只保留最近 100 条
            if len(history) > 100:
                history = history[-100:]
            existing["history"] = history
            self.save(user_id, existing)
        else:
            self.save(
                user_id,
                {
                    "user_id": user_id,
                    "preferences": {},
                    "history": [event],
                    "last_session": "",
                },
            )

    def log_event(self, user_id: str, event_type: str, details: dict) -> None:
        """记录事件日志（独立于用户记忆）."""
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO user_event_log
                   (user_id, event_type, details, created_at)
                   VALUES (?, ?, ?, ?)""",
                (user_id, event_type, json.dumps(details), now),
            )

    def query_events(self, user_id: str, event_type: Optional[str] = None, limit: int = 50) -> list[dict]:
        """查询用户事件日志."""
        with self._get_conn() as conn:
            if event_type:
                rows = conn.execute(
                    """SELECT * FROM user_event_log
                       WHERE user_id=? AND event_type=?
                       ORDER BY created_at DESC LIMIT ?""",
                    (user_id, event_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM user_event_log
                       WHERE user_id=?
                       ORDER BY created_at DESC LIMIT ?""",
                    (user_id, limit),
                ).fetchall()
            return [
                {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "event_type": row["event_type"],
                    "details": json.loads(row["details"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

    def delete_user(self, user_id: str) -> None:
        """删除用户记忆."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM user_memory WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM user_event_log WHERE user_id = ?", (user_id,))
